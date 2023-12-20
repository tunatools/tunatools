import datetime
import xml.etree.ElementTree as ET

import os
from pathlib import Path
import yaml
import re


base_path =  Path(Path(__file__).parent)
input = Path(base_path, 'data', 'raw')
output = Path(base_path, 'data', 'output')
if not input.is_dir():
    os.makedirs(input)
if not output.is_dir():
    os.makedirs(output)

def insert_sensor(tree, sensor):
    calc_array = tree.find('CalcArray')
    array_size = int(calc_array.get('Size'))
    calc_array.set('Size', str(array_size+1))
    xml = ET.parse(sensor).getroot()
    xml.set('index', str(array_size))
    calc_array.extend([xml])

def createCalcArrayItem(calcArray, object, Ordinal, index):
    calcItems = 0
    if type(object) is not list:
        object = [object]
    for x in range(Ordinal):
        for obj in object:
            calcArrayItem = ET.SubElement(calcArray, 'CalcArrayItem')
            calcArrayItem.set('index', str(index+calcItems))
            calcArrayItem.set('CalcID', str(obj['CalcID']))
            calc = ET.SubElement(calcArrayItem, 'Calc')
            calc.set('UnitID', str(obj['UnitID']))
            calc.set('Ordinal', str(x))
            fn = ET.SubElement(calc, 'FullName')
            fullname = obj['FullName']
            if x > 0:
                fullname = re.sub(r'(.*) \[(.*)\]', fr'\1, {x+1} [\2]', fullname)
            fn.set('value', fullname)
            if 'extra' in obj.keys():
                calc.extend(yaml_to_xml(obj['extra']))
            calcItems += 1
    return calcItems

def build_CalcArray(xmlcon, defaults, extras, ignore_ids, ignore_sensors):
    calcArray = ET.Element('CalcArray')
    index = 0
    sensor_types = [s.tag for s in xmlcon.findall('.//Sensor/*')]
    for default in defaults:
        # Filters and so on don't need these in their processing
        if default['UnitID'] in ignore_ids:
            continue
        index += createCalcArrayItem(calcArray, default, 1, index)
    for sensor in set(sensor_types):
        if sensor in ignore_sensors + ["NotInUse"]:
            continue
        index += createCalcArrayItem(calcArray, extras[sensor], sensor_types.count(sensor), index)
    calcArray.set('Size', str(index))
    return calcArray

def base_psa(group_of_files, ignore_ids=[-1], ignore_sensors=[]):
    suffixes = set([file.suffix.lower() for file in group_of_files])
    assert suffixes, "The group is empty!?"
    assert '.hex' in suffixes, f"The group {group_of_files[0].stem} has no .hex"
    assert '.xmlcon' in suffixes, f"The group {group_of_files[0].stem} has no .xmlcon"

    # TODO: Assert all CalcArrayItems requirements in XMLCON
    xmlcon_file = [x for x in group_of_files if x.suffix.lower() == '.xmlcon'][0]
    xmlcon = ET.parse(xmlcon_file).getroot()

    with open(Path(base_path, 'data', 'CalcArray_default.yaml')) as yaml_file:
        defaults = yaml.safe_load(yaml_file)
    with open(Path(base_path, 'data', 'CalcArray_optional.yaml')) as yaml_file:
        requirements = yaml.safe_load(yaml_file)
    calcArray = build_CalcArray(xmlcon, defaults, requirements, ignore_ids=ignore_ids, ignore_sensors=ignore_sensors)
    return xmlcon_file, calcArray

def yaml_to_xml(yaml, parent = None):
    elements = []
    for k, v in yaml.items():
        if isinstance(v, dict):
            main = ET.Element(k)
            el = yaml_to_xml(v, main)
            main.extend(el)
            elements.append(main)
        #if no parent the attributes are ignored
        elif isinstance(v, str) and parent != None:
            parent.set(k, v)
        elif (isinstance(v, int) or isinstance(v, float)) and parent != None:
            parent.set(k, str(v))
    return elements

def create_datcnv_psa(group_of_files, name, xmlcon):
    dc = ET.Element('Data_Conversion')
    main = ET.ElementTree(dc)
    root = main.getroot()
    for file_ in ['psa_base.yaml', 'psa_datcnv.yaml']:
        with open(Path(base_path, 'data', file_)) as yaml_file:
            base = yaml.safe_load(yaml_file)
        xml = yaml_to_xml(base)
        root.extend(xml)
    if '.bl' in set([file.suffix for file in group_of_files]):
        products = root.find('CreateFile')
        products.set('value', '2')
    servername = root.find('ServerName')
    servername.set('value', 'Data Conversion') # not required
    xmlcon_file, CalcArray = base_psa(group_of_files, ignore_ids=[])
    root.extend([CalcArray])
    hexfile = {file.suffix: file for file in group_of_files}
    sharktools_name, year = create_sharktools_name(xmlcon_file, hexfile['.hex'])
    root.find('./OutputFile').set('value', sharktools_name)
    psa_filename = Path(base_path, 'data', 'psa_files', f'dat_cnv_{name}.psa')
    ET.indent(main) # requires python 3.9
    main.write(psa_filename)
    return xmlcon_file, psa_filename, sharktools_name, year

def create_filter_psa(group_of_files, name):
    dc = ET.Element('Filter')
    main = ET.ElementTree(dc)
    root = main.getroot()
    with open(Path(base_path, 'data', 'psa_base.yaml')) as yaml_file:
        base = yaml.safe_load(yaml_file)
    xml = yaml_to_xml(base)
    root.extend(xml)
    root.find('ServerName').set('value', 'Filter') # not required
    xmlcon_file, CalcArray = base_psa(group_of_files)
    root.extend([CalcArray])

    fta = ET.SubElement(root, 'FilterTypeArray')

    # read in information from filter.yaml file and convert them to xml format
    with open(Path(base_path, 'data', 'psa_filter.yaml')) as yaml_file:
        filter = yaml.safe_load(yaml_file)
    xml = yaml_to_xml(filter['extra'])
    root.extend(xml)

    for arrayelement in CalcArray:
        index = arrayelement.get('index')
        fullname = arrayelement.find('.//FullName')
        # TODO: fix ,2
        if fullname.get('value') in filter:
            value = filter[fullname.get('value')]['value']
        else:
            value = 0
        ai = ET.SubElement(fta, 'ArrayItem')
        ai.set('index', str(index))
        ai.set('value', str(value))

    psa_filename = Path(base_path, 'data', 'psa_files', f'filter_{name}.psa')
    ET.indent(main) # requires python 3.9
    main.write(psa_filename)
    return psa_filename

def create_derive_psa(xmlcon_file, name):
    xmlcon = ET.parse(xmlcon_file).getroot()
    dc = ET.Element('Derive')
    main = ET.ElementTree(dc)
    root = main.getroot()
    for file_ in ['psa_base.yaml', 'psa_derive.yaml']:
        with open(Path(base_path, 'data', file_)) as yaml_file:
            base = yaml.safe_load(yaml_file)
        xml = yaml_to_xml(base)
        root.extend(xml)
    servername = root.find('ServerName')
    servername.set('value', 'Data Conversion')  # not required
    with open(Path(base_path, 'data', 'psa_derive_optional.yaml')) as yaml_file:
        requirements = yaml.safe_load(yaml_file)
    calcArray = build_CalcArray(xmlcon, [], requirements, ignore_ids=[], ignore_sensors=['FluoroWetlabECO_AFL_FL_Sensor', 'TurbidityMeter', 'Fluorometer', 'PAR_BiosphericalLicorChelseaSensor', 'FluoroWetlabCDOM_Sensor'])
    root.extend([calcArray])
    psa_filename = Path(base_path, 'data', 'psa_files', f'derive_{name}.psa')
    ET.indent(main)  # requires python 3.9
    main.write(psa_filename)
    return psa_filename


def create_sharktools_name(xmlcon_file, hexfile):
    #sbe09_{pressuresensor:04d}_{datetime.strfrmtime('%Y%m%d_%H%M')}_Ship(d2w2)_cruise_serno
    xmlcon = ET.parse(xmlcon_file).getroot()
    pressure_sensor = xmlcon.find('.//PressureSensor/SerialNumber').text
    assert pressure_sensor != ""
    with open(hexfile, 'r') as hex:
        hex_data = hex.read()
        date = re.search('^\* System UTC = ([\w \d:]*)$', hex_data, re.M)
        assert date
        meassurement_start = datetime.datetime.strptime(date[1], '%b %d %Y %H:%M:%S')
        meassurement_start_str = meassurement_start.strftime('%Y%m%d_%H%M')
        #* System UTC = May 17 2023 10:50:11
    with open(Path(base_path, 'data', 'expedition_specific.yaml'), 'r') as yaml_file:
        extra_data = yaml.safe_load(yaml_file)
    return f'sbe09_{pressure_sensor}_{meassurement_start_str}_{extra_data["ship_name"]}_{extra_data["cruise_number"]:02d}_0000.cnv', str(meassurement_start.year)


def create_alignctd_psa(group_of_files, name):
    dc = ET.Element('Align_CTD')
    main = ET.ElementTree(dc)
    root = main.getroot()
    with open(Path(base_path, 'data', 'psa_base.yaml')) as yaml_file:
        base = yaml.safe_load(yaml_file)
    xml = yaml_to_xml(base)
    root.extend(xml)
    root.find('ServerName').set('value', 'Align CTD') # not required
    #Ignore id=3 (Pressure) because all the other values are aligned against it
    #If it would be set, SBE Processing complains about pressure not being in the file
    xmlcon_file, CalcArray = base_psa(group_of_files, ignore_sensors = ['PressureSensor'])
    root.extend([CalcArray])


    aca = ET.SubElement(root, 'ValArray')

    with open(Path(base_path, 'data', 'psa_alignctd.yaml')) as yaml_file:
        alignctd = yaml.safe_load(yaml_file)
    #xml = yaml_to_xml(alignctd['extra'])
    #root.extend(xml)

    for arrayelement in CalcArray:
        index = arrayelement.get('index')
        fullname = arrayelement.find('.//FullName')

        if fullname.get('value') in alignctd:
            value = alignctd[fullname.get('value')]['value']
        else:
            value = 0
        ai = ET.SubElement(aca, 'ValArrayItem')
        ai.set('index', str(index))
        ai.set('value', str(value))
        ai.set('variable_name', str(fullname.text))

    aca.set('size', str(len(CalcArray)))

    psa_filename = Path(base_path, 'data', 'psa_files', f'alignctd_{name}.psa')
    ET.indent(main) # requires python 3.9
    main.write(psa_filename)
    return psa_filename


def build_ctd_processing():
    # read in filenames of generic psa files as defined in psa_generic.yaml
    with open(Path(base_path, 'data', 'psa_generic.yaml'),'r') as yaml_file:
        psa_filenames = yaml.safe_load(yaml_file)

    celltm_filename = Path(psa_filenames['psa_celltm'])
    loopedit_filename = Path(psa_filenames['psa_loopedit'])
    binavg_filename = Path(psa_filenames['psa_binavg'])



    with open('ctd_processing_psa.txt', 'w') as sbe_params:
        raw_data_folder = Path(base_path, 'data', 'raw')
        for path in raw_data_folder.glob('*.hex'):
            name = path.stem
            group = list(raw_data_folder.glob(f'{name}.*'))
            xmlcon_file, psa_filename, sharktools_name, year = create_datcnv_psa(group, name, path)
            output_dir = Path(base_path, 'data', 'output', year, 'cnv') #this stucture is required by sharktools
            os.makedirs(output_dir, exist_ok=True)
            sharktools_output = Path(output_dir, sharktools_name)
            derive_filename = create_derive_psa(xmlcon_file, name)
            sbe_params.write(
                f'''datcnv /p{psa_filename} /i{path} /c{xmlcon_file} /o{output_dir}\n'''
            )
            filter_filename = create_filter_psa(group, name)
            sbe_params.write(
                f'''filter /p{filter_filename} /i{sharktools_output} /o{output_dir}\n'''
            )
            alignctd_filename = create_alignctd_psa(group, name)
            sbe_params.write(
                f'''alignctd /p{alignctd_filename} /i{sharktools_output} /o{output_dir}\n'''
            )
            sbe_params.write(
                f'''celltm /p{celltm_filename} /i{sharktools_output} /o{output_dir}\n'''
            )
            sbe_params.write(
                f'''loopedit /p{loopedit_filename} /i{sharktools_output} /o{output_dir}\n'''
            )
            sbe_params.write(
                f'''derive /p{derive_filename} /i{sharktools_output} /c{xmlcon_file} /o{output_dir}\n'''
            )
            sbe_params.write(
                f'''binavg /p{binavg_filename} /i{sharktools_output} /o{output_dir}\n'''
            )


if __name__ == "__main__":
    import subprocess
    build_ctd_processing()
    subprocess.call([
        'sbebatch.exe',
        base_path / "ctd_processing_psa.txt",
        base_path / "data\output"
    ])

