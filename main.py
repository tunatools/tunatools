import xml.etree.ElementTree as ET

import os
from pathlib import Path
import yaml
import re


def insert_sensor(tree, sensor):
    calc_array = tree.find('CalcArray')
    array_size = int(calc_array.get('Size'))
    calc_array.set('Size', str(array_size+1))
    xml = ET.parse(sensor).getroot()
    xml.set('index', str(array_size))
    calc_array.extend([xml])

def createCalcArrayItem(calcArray, object, Ordinal, index):
    calcArrayItem = ET.SubElement(calcArray, 'CalcArrayItem')
    calcArrayItem.set('index', str(index))
    calcArrayItem.set('CalcID', str(object['CalcID']))
    calc = ET.SubElement(calcArrayItem, 'Calc')
    calc.set('UnitID', str(object['UnitID']))
    calc.set('Ordinal', str(Ordinal))
    fn = ET.SubElement(calc, 'FullName')
    fullname = object['FullName']
    if Ordinal > 0:
        fullname = re.sub(r'(.*) \[(.*)\]', fr'\1, {Ordinal+1} [\2]', fullname)
    fn.text= fullname
    if 'extra' in object.keys():
        calc.extend(yaml_to_xml(object['extra']))
def build_CalcArray(xmlcon, defaults, extras, ignore_ids=[]):
    calcArray = ET.Element('CalcArray')
    index = 0
    for default in defaults:
        # Filters and so on don't need these in their processing
        if default['UnitID'] in ignore_ids:
            continue
        same_type = calcArray.findall(f'.//CalcArrayItem[@CalcID="{default["CalcID"]}"]')
        createCalcArrayItem(calcArray, default, len(same_type), index)
        index += 1
    sensor_types = [s.tag for s in xmlcon.findall('.//Sensor/*')]
    for req, extra in extras.items():
        if sensor_types.count(req) >= extra['counts']:
            if default['UnitID'] in ignore_ids:
                continue
            same_type = calcArray.findall(f'.//CalcArrayItem[@CalcID="{extra["CalcID"]}"]')
            createCalcArrayItem(calcArray, extra, len(same_type), index)
            index += 1
    calcArray.set('Size', str(index))
    return calcArray

def base_psa(group_of_files, ignore_ids=[-1]):
    suffixes = set([file.suffix for file in group])
    assert suffixes, "The group is empty!?"
    assert '.hex' in suffixes, f"The group {group_of_files[0].stem} has no .hex"
    assert '.xmlcon' in suffixes, f"The group {group_of_files[0].stem} has no .xmlcon"

    # TODO: Assert all CalcArrayItems requirements in XMLCON
    xmlcon_file = Path(raw_data_folder, f"{name}.xmlcon")
    xmlcon = ET.parse(xmlcon_file).getroot()

    with open(Path(base_path, 'data', 'CalcArray_default.yaml')) as yaml_file:
        defaults = yaml.safe_load(yaml_file)
    with open(Path(base_path, 'data', 'CalcArray_optional.yaml')) as yaml_file:
        requirements = yaml.safe_load(yaml_file)
    calcArray = build_CalcArray(xmlcon, defaults, requirements, ignore_ids=ignore_ids)
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

base_path =  Path(Path(__file__).parent)

def create_datcnv_psa(group_of_files, name):
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
    psa_filename = Path(base_path, 'data', 'psa_files', f'dat_cnv_{name}.psa')
    ET.indent(main) # requires python 3.9
    main.write(psa_filename)
    return xmlcon_file, psa_filename

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
        # TODO: remove pump status, count
        if fullname.text in filter:
            value = filter[fullname.text]['value']
        else:
            value = 0
        ai = ET.SubElement(fta, 'ArrayItem')
        ai.set('index', str(index))
        ai.set('value', str(value))

    psa_filename = Path(base_path, 'data', 'psa_files', f'filter_{name}.psa')
    ET.indent(main) # requires python 3.9
    main.write(psa_filename)
    return psa_filename

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
    xmlcon_file, CalcArray = base_psa(group_of_files, ignore_ids=[-1, 3])
    root.extend([CalcArray])


    aca = ET.SubElement(root, 'ValArray')

    with open(Path(base_path, 'data', 'psa_alignctd.yaml')) as yaml_file:
        alignctd = yaml.safe_load(yaml_file)
    #xml = yaml_to_xml(alignctd['extra'])
    #root.extend(xml)

    for arrayelement in CalcArray:
        index = arrayelement.get('index')
        fullname = arrayelement.find('.//FullName')

        if fullname.text in alignctd:
            value = alignctd[fullname.text]['value']
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

# read in filenames of generic psa files as defined in psa_generic.yaml
with open(Path(base_path, 'data', 'psa_generic.yaml'),'r') as yaml_file:
    psa_filenames = yaml.safe_load(yaml_file)

celltm_filename = Path(psa_filenames['psa_celltm'])
loopedit_filename = Path(psa_filenames['psa_loopedit'])
derive_filename = Path(psa_filenames['psa_derive'])
binavg_filename = Path(psa_filenames['psa_binavg'])



with open('ctd_processing_psa.txt', 'w') as sbe_params:
    raw_data_folder = Path(base_path, 'data', 'raw')
    for path in raw_data_folder.glob('*.hex'):
        name = path.stem
        group = list(raw_data_folder.glob(f'{name}.*'))
        xmlcon_file, psa_filename = create_datcnv_psa(group, name)
        sbe_params.write(
            f'''datcnv /p{psa_filename} /i{path} /c{xmlcon_file} /o{Path(base_path, 'data', 'output')}\n'''
        )
        filter_filename = create_filter_psa(group, name)
        sbe_params.write(
            f'''filter /p{filter_filename} /i{Path(base_path, 'data', 'output', name+'.cnv')} /o{Path(base_path, 'data','output')}\n'''
        )
        alignctd_filename = create_alignctd_psa(group, name)
        sbe_params.write(
            f'''alignctd /p{alignctd_filename} /i{Path(base_path, 'data', 'output', name+'.cnv')} /o{Path(base_path, 'data','output')}\n'''
        )
        sbe_params.write(
            f'''celltm /p{celltm_filename} /i{Path(base_path, 'data', 'output', name+'.cnv')} /o{Path(base_path, 'data','output')}\n'''
        )
        sbe_params.write(
            f'''loopedit /p{loopedit_filename} /i{Path(base_path, 'data', 'output', name+'.cnv')} /o{Path(base_path, 'data','output')}\n'''
        )
        sbe_params.write(
            f'''derive /p{derive_filename} /i{Path(base_path, 'data', 'output', name+'.cnv')} /c{xmlcon_file} /o{Path(base_path, 'data','output')}\n'''
        )
        sbe_params.write(
            f'''binavg /p{binavg_filename} /i{Path(base_path, 'data', 'output', name+'.cnv')} /o{Path(base_path, 'data','output')}\n'''
        )



import subprocess
subprocess.call([
    'sbebatch.exe',
    base_path / "ctd_processing_psa.txt",
    base_path / "data\output"
])

