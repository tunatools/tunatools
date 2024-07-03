import datetime
import os
import yaml
import re
import xml.etree.ElementTree as ET
from pathlib import Path, WindowsPath, PosixPath
import warnings
import subprocess
import shutil
import sys


def get_base_path() -> Path:
    return Path(Path(__file__).parent)


# To maintain compatibility with older pythons we had to remove some hints
# def yaml_to_xml(yaml_object, parent=None) -> list[ET.Element]:
def yaml_to_xml(yaml_object, parent=None):
    """Casts a yaml object (dict of dicts) into a xml.
    This function is mainly used to cast our configuration files to psa files."""
    elements = []
    for k, v in yaml_object.items():
        if isinstance(v, dict):
            main = ET.Element(k)
            el = yaml_to_xml(v, main)
            main.extend(el)
            elements.append(main)
        # if no parent the attributes are ignored
        elif isinstance(v, str) and parent is not None:
            parent.set(k, v)
        elif (isinstance(v, int) or isinstance(v, float)) and parent is not None:
            parent.set(k, str(v))
    return elements


def createCalcArrayItem(calc_array, sensor_dependant_items, amount=1, index=0):
    """Creates 'amount' entries of CalcArrayItems of the type 'sensor_dependant_items'.
    Takes care of upticking the index and ordinal. That is to produce SBE Oxygen 2,[]
    if there is two or more OxygenSensors"""
    calc_items = 0
    if type(sensor_dependant_items) is not list:
        sensor_dependant_items = [sensor_dependant_items]
    for x in range(amount):
        for obj in sensor_dependant_items:
            calcArrayItem = ET.SubElement(calc_array, 'CalcArrayItem')
            calcArrayItem.set('index', str(index+calc_items))
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
            calc_items += 1
    return calc_items


def build_CalcArray(xmlcon_str: ET, defaults, extras, ignore_ids: list[int], ignore_sensors: list[str]):
    """Builds the complete CalcArray based on the provided xmlcon.
    defaults is a list of the measurements we will always have: pump status, scan count, etc.
    extras is a list of the """
    calc_array = ET.Element('CalcArray')
    index = 0
    sensor_types = [s.tag for s in xmlcon_str.findall('.//Sensor/*')]
    for default in defaults:
        # Filters and so on don't need these in their processing
        if default['UnitID'] in ignore_ids:
            continue
        index += createCalcArrayItem(calc_array, default, 1, index)
    for sensor in set(sensor_types):
        if sensor in ignore_sensors + ["NotInUse"]:
            continue
        try:
            index += createCalcArrayItem(calc_array, extras[sensor], sensor_types.count(sensor), index)
        except KeyError:
            raise KeyError(f"Looks like your CalcArray_optional.yaml doesn't contain a {sensor}")
    calc_array.set('Size', str(index))
    return calc_array


def calcArray_from_xmlcon(xmlcon_file: Path, ignore_ids=[-1], ignore_sensors: list[str] = [],
                          default: str | None = "CalcArray_default.yaml",
                          optional: str | None = "CalcArray_optional.yaml"):
    xmlcon_xml = ET.parse(xmlcon_file).getroot()
    base_path = get_base_path()
    if default:
        with open(Path(base_path, 'data', default)) as yaml_file:
            defaults = yaml.safe_load(yaml_file)
    else:
        defaults = []
    if optional:
        with open(Path(base_path, 'data', optional)) as yaml_file:
            requirements = yaml.safe_load(yaml_file)
    else:
        requirements = []
    calcArray = build_CalcArray(xmlcon_xml, defaults, requirements,
                                ignore_ids=ignore_ids, ignore_sensors=ignore_sensors)
    return calcArray


# def build_base_psa(name:str, xmlcon_file: Path, base_config: list[str] = None,
def build_base_psa(name: str, xmlcon_file: Path, base_config=None,
                   ignore_ids=[-1], ignore_sensors=[],
                   default: str | None = "CalcArray_default.yaml",
                   optional: str | None ="CalcArray_optional.yaml"):
    base_path = get_base_path()
    main_element = ET.Element(name)
    main = ET.ElementTree(main_element)
    root = main.getroot()
    for config_file in base_config:
        with open(Path(base_path, 'data', config_file)) as yaml_file:
            base = yaml.safe_load(yaml_file)
        xml = yaml_to_xml(base)
        root.extend(xml)
    calcArray = calcArray_from_xmlcon(xmlcon_file,
                ignore_ids=ignore_ids, ignore_sensors=ignore_sensors,
                default=default, optional=optional)
    root.extend([calcArray])
    return main


def fix_lat_lon(et_tree: ET, coords: (float, float)):
    '''Sets the latitude and longitude in the tree to the tuple provided.'''
    if coords:
        coords = map(str, coords)
        lat, lon = coords
        et_tree.find('.//Latitude').set('value', lat)
        et_tree.find('.//Longitude').set('value', lon)


def is_windows_path(obj) -> bool:
    """Checks if the object is a valid Path under Windows"""
    # PosixPath is here because my Windows decided not to boot and now I'm developing on Linux
    return type(obj) in [Path, WindowsPath, PosixPath]


class SBE911_Measurement:
    def __init__(self, *args, **kwargs):
        """An object containing the required files for a measurement.\n
        The paths of the created psa are saved in the psa_dict.\n
        At least a xmlcon and hex file are required to do any processing (as dict, list, attributes).
        If only one of these is provided it is assumed that the other one shares the stem.
        """
        self.xmlcon = None
        self.hex = None
        self.bl = None
        self.psa_dict = dict()

        self.source_folder = Path(kwargs.get('source_folder', 'data/raw'))
        self.psa_folder = Path(kwargs.get('psa_folder', 'data/psa_files'))
        self.output_folder = Path(kwargs.get('output_folder', 'data/output'))

        # Make everything absolute paths
        for folder in ['source_folder', 'psa_folder', 'output_folder']:
            if not getattr(self, folder).is_absolute():
                setattr(self, folder, getattr(self, folder).absolute())
        self.batch_file = None

        # We will try to save stuff here, so we better be sure that they exist
        for folder in [self.psa_folder, self.output_folder]:
            if not folder.is_dir():
                os.makedirs(folder)

        if len(args) == 1:
            # AOM23-station-04-cast1 or Path(...)
            args = args[0]

            if type(args) is str:
                args = Path(args)
            if is_windows_path(args):
                if args.is_absolute():
                    self.source_folder = args.parent
                args = list(self.source_folder.glob(f'{args.stem}.*'))
                args = [arg.absolute() for arg in args]

        # [AOM23-station-04-cast1.xmlcon, AOM23-station-04-cast1.hex, AOM23-station-04-cast1.bl, ...]
        if type(args) is list or type(args) is tuple:
            args_dict = dict()
            if any(type(arg) is str for arg in args):
                args = list(map(Path, args))
            xmlcon_files = [x for x in args if x.suffix.lower() == '.xmlcon']
            assert len(xmlcon_files) == 1, \
                f"The group {args[0].stem} does not have a .xmlcon file"
            args_dict['xmlcon'] = xmlcon_files[0]

            hex_files = [x for x in args if x.suffix.lower() == '.hex']
            assert len(hex_files) == 1, \
                f"The group {args[0].stem} does not have a .hex file"
            args_dict['hex'] = hex_files[0]

            bl_files = [x for x in args if x.suffix.lower() == '.bl']
            assert len(hex_files) <= 1, \
                f"The group {args[0].stem} has more than a .bl file"
            if bl_files:
                args_dict['bl'] = bl_files[0]
            args = args_dict

        # {'xmlcon': Path/str, 'hex': Path/str}
        if type(args) is dict:
            xmlcon = args.get('xmlcon')
            hex_file = args.get('hex')
            assert (xmlcon and hex_file), \
                "Your dictionary does not have a xmlcon AND a hex file."
            bl = args.get('bl')

            if not is_windows_path(xmlcon):
                xmlcon = Path(xmlcon)
            self.xmlcon = xmlcon

            if not is_windows_path(hex_file):
                hex_file = Path(hex_file)
            self.hex = hex_file
            if bl:
                if not is_windows_path(bl):
                    bl = Path(bl)
                self.bl = bl

        # Make everything absolute paths (again)
        for file in ['xmlcon', 'hex', 'bl']:
            if getattr(self, file) and not getattr(self, file).is_absolute():
                setattr(self, file, Path(self.source_folder, getattr(self, file)))

    def parse_lat_lon(self) -> (float, float):
        """Parses the hexfile and looks for NMEA coordinates. Parses them from degrees
        and decimal minutes (DD) to degrees."""
        with open(self.hex, 'r') as opened_hex_file:
            hex_content = opened_hex_file.read()
        lat = re.search(r'^\* NMEA Latitude = (\d{2}) ([\d\.]+) (\w)$',
                        hex_content, re.M)
        lon = re.search(r'^\* NMEA Longitude = (\d{3}) ([\d\.]+) (\w)$',
                        hex_content, re.M)
        if not lat or not lon:
            warnings.warn(
                f"Your hexfile ({self.hex.stem}) doesn't have coordinates! SHARKtools will fail!")
            return None
        d, m, SN = lat.groups()
        lat_DD = (-1 if SN == "S" else 1) * (int(d) + float(m) / 60.)
        d, m, EW = lon.groups()
        lon_DD = (-1 if EW == "W" else 1) * (int(d) + float(m) / 60.)
        return lat_DD, lon_DD

    def create_datcnv_psa(self, force: bool = False) -> Path:
        psa_filename = Path(self.psa_folder,
                            f'dat_cnv_{self.hex.stem+".psa"}')
        if force or not psa_filename.is_file():
            coords = self.parse_lat_lon()
            ignore_ids = []
            if not coords:
                ignore_ids += [4]
            main = build_base_psa('Data_Conversion', self.xmlcon,
                                  ['psa_base.yaml', 'psa_datcnv.yaml'],
                                  ignore_ids=ignore_ids)
            root = main.getroot()

            if self.bl:
                products = root.find('CreateFile')
                products.set('value', '2')

            root.find('ServerName').set('value', 'Data Conversion')  # not required
            fix_lat_lon(root, coords)
            # For backward compatibility (SHARKtools ran only on python 3.8)
            if sys.version_info >= (3, 9):
                ET.indent(main)
            main.write(psa_filename)
        self.psa_dict['datcnv'] = psa_filename
        return psa_filename

    def create_filter_psa(self, force=False) -> Path:
        psa_filename = Path(self.psa_folder, f'filter_{self.hex.stem+".psa"}')
        if force or not psa_filename.is_file():
            coords = self.parse_lat_lon()
            ignore_ids = [-1]
            if not coords:
                ignore_ids += [4]
            main = build_base_psa('Filter', self.xmlcon,
                                  ['psa_base.yaml'], ignore_ids=ignore_ids)
            root = main.getroot()

            fta = ET.SubElement(root, 'FilterTypeArray')

            # read in information from filter.yaml file and convert them to xml format
            with open(Path(self.psa_folder, 'psa_filter.yaml')) as yaml_file:
                filter = yaml.safe_load(yaml_file)
            xml = yaml_to_xml(filter['extra'])
            root.extend(xml)

            for arrayelement in root.findall('.//CalcArrayItem'):
                index = arrayelement.get('index')
                fullname = arrayelement.find('.//FullName')
                if fullname.get('value') in filter:
                    value = filter[fullname.get('value')]['value']
                else:
                    value = 0
                ai = ET.SubElement(fta, 'ArrayItem')
                ai.set('index', str(index))
                ai.set('value', str(value))

            if sys.version_info >= (3, 9):
                ET.indent(main)
            main.write(psa_filename)
        self.psa_dict['filter'] = psa_filename
        return psa_filename

    def create_alignctd_psa(self, force=False) -> Path:
        psa_filename = Path(self.psa_folder, f'alignctd_{self.hex.stem}.psa')
        if force or not psa_filename.is_file():
            coords = self.parse_lat_lon()
            ignore_ids = [-1]
            if not coords:
                ignore_ids += [4]
            # Ignore id=3 (Pressure) because all the other values are aligned against it
            # If it would be set, SBE Processing complains about pressure not being in the file
            main = build_base_psa('Align_CTD', self.xmlcon,
                                  ['psa_base.yaml'], ignore_ids=ignore_ids, ignore_sensors=['PressureSensor'])
            root = main.getroot()
            aca = ET.SubElement(root, 'ValArray')

            with open(Path(get_base_path(), 'data', 'psa_alignctd.yaml')) as yaml_file:
                alignctd = yaml.safe_load(yaml_file)

            for arrayelement in root.findall('.//CalcArrayItem'):
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

            aca.set('size', str(len(root.findall('.//CalcArrayItem'))))

            if sys.version_info >= (3, 9):
                ET.indent(main)
            main.write(psa_filename)
        self.psa_dict['alignctd'] = psa_filename
        return psa_filename

    def create_derive_psa(self, force=False) -> Path:
        psa_filename = Path(self.psa_folder, f'derive_{self.hex.stem}.psa')
        if force or not psa_filename.is_file():
            coords = self.parse_lat_lon()
            ignore_ids = [-1]
            if not coords:
                ignore_ids += [4]
            main = build_base_psa('Derive', self.xmlcon,
                                  ['psa_base.yaml', 'psa_derive.yaml'], ignore_ids=ignore_ids,
                                  default=None, optional="psa_derive_optional.yaml",
                                  ignore_sensors=[
                                            'FluoroWetlabECO_AFL_FL_Sensor',
                                            'TurbidityMeter', 'Fluorometer',
                                            'PAR_BiosphericalLicorChelseaSensor',
                                            'SPAR_Sensor',
                                            'FluoroWetlabCDOM_Sensor'])
            root = main.getroot()
            aca = ET.SubElement(root, 'ValArray')
            root.find('ServerName').set('value', 'Data Conversion')
            if sys.version_info >= (3, 9):
                ET.indent(main)
            main.write(psa_filename)
        self.psa_dict['derive'] = psa_filename
        return psa_filename

    def create_celltm_psa(self):
        psa_filename = Path(self.psa_folder, 'celltm_generic.psa')
        self.psa_dict['celltm'] = psa_filename
        return psa_filename

    def create_binavg_psa(self):
        psa_filename = Path(self.psa_folder, 'binavg_generic.psa')
        self.psa_dict['binavg'] = psa_filename
        return psa_filename

    def create_loopedit_psa(self):
        psa_filename = Path(self.psa_folder, 'loopedit_generic.psa')
        self.psa_dict['loopedit'] = psa_filename
        return psa_filename

    def create_bottlesum_psa(self, force=False):
        """Creates a psa for the bottlesum function."""
        psa_filename = Path(self.psa_folder, f'bottlesum_{self.hex.stem}.psa')
        if force or not psa_filename.is_file():
            coords = self.parse_lat_lon()
            ignore_ids = [-1]
            if not coords:
                ignore_ids += [4]
            ignore_sensors = ['FluoroWetlabECO_AFL_FL_Sensor',
                              'TurbidityMeter', 'Fluorometer',
                              'PAR_BiosphericalLicorChelseaSensor',
                              'SPAR_Sensor',
                              'FluoroWetlabCDOM_Sensor']
            main = build_base_psa('Bottle_Summary', self.xmlcon,
                                  ['psa_base.yaml', 'psa_bottlesum.yaml'],
                                  ignore_ids=ignore_ids,
                                  ignore_sensors=ignore_sensors)
            root = main.getroot()
            average_array = root.find('CalcArray')
            # The bottlesum has 3 parts. The first one is the same format as datcnv.
            average_array.tag = 'AverageCalcArray'

            # The second one marks which ones should be selected. We set all to 1, allowing all to be calculated.
            aca = ET.SubElement(root, 'SelectArray')
            for item in average_array:
                t = ET.SubElement(aca, 'ArrayItem')
                t.set('index', item.get('index'))
                t.set('value', '1')

            derive_array = calcArray_from_xmlcon(self.xmlcon, ignore_ids=ignore_ids, ignore_sensors=ignore_sensors,
                                                 default=None, optional='psa_derive_optional.yaml')

            derive_array.tag = 'DeriveCalcArray'
            root.extend([derive_array])

            root.find('ServerName').set('value', 'Bottle_Summary')  # not required

            if sys.version_info >= (3, 9):
                ET.indent(main)
            main.write(psa_filename)
        self.psa_dict['bottlesum'] = psa_filename
        return psa_filename

    def create_all_psa(self, force=False):
        self.create_datcnv_psa(force)
        self.create_filter_psa(force)
        self.create_alignctd_psa(force)
        self.create_celltm_psa()
        self.create_loopedit_psa()
        self.create_derive_psa(force)
        self.create_binavg_psa()
        if self.bl:
            self.create_bottlesum_psa(force)

    def create_sbe_batch_file(self, force: bool = False):
        batch_name = Path(self.psa_folder, f'batch_{self.hex.stem+".txt"}')
        if force or not batch_name.is_file():
            require_xmlcon = ['datcnv', 'derive']
            with open(batch_name, 'w') as sbe_params:
                for name, file in self.psa_dict.items():
                    sbe_params.write(
                        f'{name} /p{file} /o{self.output_folder}' +
                        (f' /c{self.xmlcon}' if name in require_xmlcon else '') +
                        f' /i{self.hex if name=="datcnv" else Path(self.output_folder, self.hex.name).with_suffix(".cnv")}' +
                        '\n'
                    )
        self.batch_file = batch_name
        return batch_name

    def run_batch(self):
        subprocess.call([
            'sbebatch.exe',
            self.batch_file,
            self.output_folder
        ])

    def just_do_stuff(self, force: bool = True):
        self.create_all_psa(force=force)
        self.create_sbe_batch_file(force=force)
        self.run_batch()


class SHARKTOOLS_Measurement(SBE911_Measurement):
    """And SBE911 measurement with special changes done so the resulting files can be run through SHARKTOOLS"""
    def build_sharktools_name(self) -> Path:
        """sbe09_{pressuresensor:04d}_{datetime.strfrmtime('%Y%m%d_%H%M')}_Ship(d2w2)_cruise_serno"""
        xmlcon = ET.parse(self.xmlcon).getroot()
        pressure_sensor = xmlcon.find('.//PressureSensor/SerialNumber').text
        assert pressure_sensor != ""
        with open(self.hex, 'r') as hex:
            hex_data = hex.read()
            date = re.search(r'^\* System UTC = ([\w \d:]*)$', hex_data, re.M)
            assert date
            measurement_start = datetime.datetime.strptime(date[1],'%b %d %Y %H:%M:%S')
            measurement_start_str = measurement_start.strftime('%Y%m%d_%H%M')
            # * System UTC = May 17 2023 10:50:11
        with open(Path(get_base_path(), 'data', 'expedition_specific.yaml'),
                  'r') as yaml_file:
            extra_data = yaml.safe_load(yaml_file)
        return Path(str(measurement_start.year), 'cnv', f'sbe09_{pressure_sensor}_{measurement_start_str}_{extra_data["ship_name"]}_{extra_data["cruise_number"]:02d}_0000.cnv')

    def rename(self, destination_folder="data/output"):
        cnv_name = Path(self.output_folder, f'{self.hex.stem + ".cnv"}')
        sharktools_name = Path(destination_folder, self.build_sharktools_name())
        if not cnv_name.is_file():
            raise FileNotFoundError("Have you processed the file?")
        if not sharktools_name.parent.is_dir():
            os.makedirs(sharktools_name.parent)
        shutil.copyfile(cnv_name, sharktools_name)

    def fix_units(self, destination_folder="data/output"):
        """SHARKtools will crash if the Licor sensor has no units (specifically if there is no [] in the name)"""
        sharktools_name = Path(destination_folder, self.build_sharktools_name())
        if not sharktools_name.is_file():
            raise FileNotFoundError("Have you created a sharktools conform named file?")
        with open(sharktools_name, 'r') as sharktools_file:
            data = sharktools_file.read()
        with open(sharktools_name, 'w') as sharktools_file:
            sharktools_file.write(data.replace('par: PAR/Irradiance, Biospherical/Licor', 'par: PAR/Irradiance, Biospherical/Licor [µE/(cm^2*s)]'))

    def just_do_stuff(self, force: bool = True,  destination_folder: str | Path ="data/select_this_one_for_sharktools"):
        self.create_all_psa(force=force)
        self.create_sbe_batch_file(force=force)
        self.run_batch()
        self.rename(destination_folder)
        self.fix_units(destination_folder)
