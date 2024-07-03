import os

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMainWindow,
    QGridLayout,
    QWidget,
    QPushButton,
    QFileDialog,
    QPlainTextEdit,
    QMessageBox,
    QLineEdit,
)
from PyQt6.QtCore import QProcess, QCoreApplication
from PyQt6.QtGui import QIcon, QDoubleValidator
import pathlib
import tunatools
import sys
import re
import datetime
import dateutil.parser
from multiprocessing import Pool


class GetCoordinates(QMainWindow):
    def __init__(self, measurement):
        super().__init__(parent=None)
        self.setWindowTitle("Fixing missing coordinates")

        widget = QWidget()
        # width, height
        self.resize(300, 160)
        layout = QGridLayout()
        widget.setLayout(layout)
        #self.setWindowIcon(QIcon(':/icons/icon'))

        self.lat = QLineEdit()
        self.lat.setValidator(QDoubleValidator(-90., 90., 2))

        self.lon = QLineEdit()
        self.lon.setValidator(QDoubleValidator(-180., 180., 2))

        layout.addWidget(QLabel('Your measurement {measurement.hex} is missing coordinates. If this should work with SHARKtools fix them here'), 0, 0, 1, 2)

        layout.addWidget(QLabel('lat (N/S)'), 1, 0)
        layout.addWidget(QLabel('lon (E/W)'), 2, 0)
        layout.addWidget(self.lat, 1, 1)
        layout.addWidget(self.lon, 2, 1)

        continue_button = QPushButton('Continue')
        continue_button.clicked.connect(self.parse_coords)
        self.setCentralWidget(widget)

    def parse_coords(self):
        try:
            lat = float(self.lat.value)
            lon = float(self.lon.value)
        except ValueError:
            pass
        return lat, lon


class modified_Measurement(tunatools.SHARKTOOLS_Measurement):
    """An SBE911 Measurement with some overwrites to the class to make coordinates fixable on the flight!"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shadow_hex()
        self.shadow_xmlcon()

    def shadow_hex(self) -> None:
        """
        SHARKtools crashes if there is no NMEA Latitude and Longitude.\n
        So we offer the possibility to make a shadow file with a modified header.\n
        This function fetches the shadow file if it exists and else allows for the creation.
        """
        with open(self.hex, 'r') as opened_hex_file:
            hex_content = opened_hex_file.read()

        # This assumes coordinates in the format 35 37.78 S. We don't know NMEA showing different data.
        # In general maybe parsing should be outsourced.
        lat = re.search(r'^\* NMEA Latitude = (\d{2}) ([\d\.]+) (\w)$',
                        hex_content, re.M)
        lon = re.search(r'^\* NMEA Longitude = (\d{3}) ([\d\.]+) (\w)$',
                        hex_content, re.M)
        lat_DD, lon_DD = None, None
        if lat:
            d, m, SN = lat.groups()
            lat_DD = (-1 if SN == "S" else 1) * (int(d) + float(m) / 60.)
        if lon:
            d, m, EW = lon.groups()
            lon_DD = (-1 if EW == "W" else 1) * (int(d) + float(m) / 60.)
        if not lat_DD or not lon_DD:
            shadow_folder = pathlib.Path(self.hex.parent, 'shadow')
            if not shadow_folder.is_dir():
                os.makedirs(shadow_folder)
            shadow_file = pathlib.Path(shadow_folder, self.hex.name)
            if shadow_file.is_file():
                self.hex = shadow_file
                return
            coords = get_coords(self, lat_DD, lon_DD)
            if coords:
                lat_DD, lon_DD = coords
                lat = f'* NMEA Latitude = {int(abs(lat_DD)):02d} {abs(lat_DD)%1*60:4.2f} {"N" if lat_DD>0 else "S"}'
                lon = f'* NMEA Longitude = {int(abs(lon_DD)):03d} {abs(lon_DD)%1*60:4.2f} {"E" if lat_DD>0 else "W"}'
                with open(shadow_file, 'w') as opened_hex_file:
                    opened_hex_file.write(hex_content.replace('* NMEA UTC (Time)', f'{lat}\n{lon}\n* NMEA UTC (Time)'))
                self.hex = shadow_file

    def shadow_xmlcon(self) -> None:
        """
        SHARKtools crashes if the calibration date of an instrument is not in one of a few
        predetermined formats, hence we create a shadow xmlcon with the fixed date.
        This function fetches the shadow file if it exists and else creates it.
        """
        """
        While we could directly use dateutil.parser.parse and reparse them to a format we're sure
        SHARKtools recognizes, this would result in a ton of shadow files. So we go through the
        formats SHARKtools uses and keep the file intact if everything would be understood.
        """
        formats_sharktools_understands = [
            '%d%m%y',
            '%d%m%Y',
            '%d-%b-%y',
            '%d-%b-%Y',
            '%d %b %y',
            '%d %b %Y'
        ]
        shadow = False
        shadow_folder = pathlib.Path(self.xmlcon.parent, 'shadow')
        shadow_file = pathlib.Path(shadow_folder, self.xmlcon.name)

        with open(self.xmlcon, 'r') as opened_xmlcon_file:
            xmlcon_content = opened_xmlcon_file.read()
        dates = re.findall(r'<CalibrationDate>(.*?)</CalibrationDate>', xmlcon_content)
        for date in dates:
            if not date:
                continue
            try:
                for format in formats_sharktools_understands:
                    try:
                        datetime.datetime.strptime(date, format)
                    except ValueError:
                        # try the next format if this one doesn't work
                        continue
                    else:
                        # this means something worked so we can skip this date
                        raise StopIteration
            except StopIteration:
                # continue with the next date
                continue
            else:
                # None of the formats worked!
                shadow = True
                new_date = ''
                try:
                    #You can pick any of the formats. This is personal preference
                    new_date = dateutil.parser.parse(date).strftime(formats_sharktools_understands[3])
                except dateutil.parser.ParserError:
                    # Even dateutil doesn't know what this is suposed to says...
                    # So we're fine just removing it! (If this doesn't work we can make the date 01/01/1970
                    pass
                finally:
                    xmlcon_content = xmlcon_content.replace(date, new_date)
        if shadow:
            if not shadow_folder.is_dir():
                os.makedirs(shadow_folder)

            old_content = None
            if shadow_file.is_file():
                with open(shadow_file, 'r') as opened_xmlcon_file:
                    old_content = opened_xmlcon_file.read()
            if old_content != xmlcon_content:
                with open(shadow_file, 'w') as opened_xmlcon_file:
                    opened_xmlcon_file.write(xmlcon_content)
            self.xmlcon = shadow_file


def get_coords(measurement, lat=None, lon=None):
    """A pop up for the user to input coordinates"""
    dialog = QDialog()
    layout = QGridLayout()
    dialog.setLayout(layout)

    lat = QLineEdit(lat)
    lat.setValidator(QDoubleValidator(-90., 90., 2))

    lon = QLineEdit(lon)
    lon.setValidator(QDoubleValidator(-180., 180., 2))

    layout.addWidget(QLabel(
        f'Your measurement {measurement.hex.name} is missing coordinates.\nIf this should work with SHARKtools fix them here'),
                     0, 0, 1, 2)

    layout.addWidget(QLabel('lat (N/S)'), 1, 0)
    layout.addWidget(lat, 1, 1)

    layout.addWidget(QLabel('lon (E/W)'), 2, 0)
    layout.addWidget(lon, 2, 1)

    continue_button = QPushButton('Continue')
    layout.addWidget(continue_button, 3, 0, 1, 2)

    continue_button.clicked.connect(dialog.close)
    dialog.exec()
    try:
        lat_DD = float(lat.text())
    except ValueError:
        return None
    try:
        lon_DD = float(lon.text())
    except ValueError:
        return None
    return lat_DD, lon_DD


class Window(QMainWindow):
    def __init__(self):
        super().__init__(parent=None)
        self.setWindowTitle("PSA Creator")

        widget = QWidget()
        # width, height
        self.resize(300, 160)
        layout = QGridLayout()
        widget.setLayout(layout)

        single_file = QPushButton('Process a file')
        folder = QPushButton('Process a folder')

        layout.addWidget(single_file, 0, 0)
        layout.addWidget(folder, 1, 0)

        single_file.clicked.connect(self.select_file)
        folder.clicked.connect(self.select_folder)
        self.setCentralWidget(widget)

    def select_folder(self):
        self.directory = QFileDialog.getExistingDirectory(self, 'Select Folder')
        if self.directory:
            widget = QWidget()
            layout = QGridLayout()
            widget.setLayout(layout)

            layout.addWidget(QLabel('Found the following files:'), 0, 0)
            venv_box = QPlainTextEdit()
            venv_box.setReadOnly(True)
            layout.addWidget(venv_box, 1, 0)
            self.continue_button = QPushButton('Continue', enabled=False)
            layout.addWidget(self.continue_button, 2, 0)

            self.setCentralWidget(widget)
            QCoreApplication.processEvents()

            self.measurements = []
            for file in pathlib.Path(self.directory).glob('*.hex'):
                try:
                    sm = modified_Measurement(file, source_folder=file.parent)
                except AssertionError as e:
                    venv_box.appendPlainText(f'{file} failed with error: {e}')
                else:
                    self.measurements.append(sm)
                    venv_box.appendPlainText(f'{sm.hex.name} with xmlcon{"+bl" if getattr(sm, "bl", None) else ""}')
            self.continue_button.setText(f'Continue with {len(self.measurements)} files')
            self.continue_button.setEnabled(True)
            self.continue_button.clicked.connect(self.process)

    def get_a_file(self, filter=None):
        a_file = QFileDialog.getOpenFileName(self, 'Select a hexfile', filter=filter)
        if a_file:
            return a_file[0]
        else:
            return None
    def select_file(self):
        self.hex = self.get_a_file("*.hex")
        if self.hex:
            measurement = modified_Measurement(self.hex)

            widget = QWidget()
            layout = QGridLayout()
            widget.setLayout(layout)
            layout.addWidget(QLabel('hexfile'), 0, 0)
            layout.addWidget(QLabel(str(measurement.hex)), 0, 1)
            layout.addWidget(QLabel('XMLCON'), 1, 0)
            layout.addWidget(QLabel(str(measurement.xmlcon)), 1, 1)
            continue_button = QPushButton('Continue')
            layout.addWidget(continue_button, 2, 0, 1, 2)
            self.setCentralWidget(widget)
        '''
        if self.directory:
            widget = QWidget()
            layout = QGridLayout()
            widget.setLayout(layout)

            layout.addWidget(QLabel('Found the following files:'), 0, 0)
            venv_box = QPlainTextEdit()
            venv_box.setReadOnly(True)
            layout.addWidget(venv_box, 1, 0)
            self.continue_button = QPushButton('Continue', enabled=False)
            layout.addWidget(self.continue_button, 2, 0)

            self.setCentralWidget(widget)
            QCoreApplication.processEvents()

            self.measurements = []
            for file in pathlib.Path(self.directory).glob('*.hex'):
                try:
                    sm = modified_Measurement(file, source_folder=file.parent)
                except AssertionError as e:
                    venv_box.appendPlainText(f'{file} failed with error: {e}')
                else:
                    self.measurements.append(sm)
                    venv_box.appendPlainText(f'{sm.hex.name} with xmlcon{"+bl" if getattr(sm, "bl", None) else ""}')
            self.continue_button.setText(f'Continue with {len(self.measurements)} files')
            self.continue_button.setEnabled(True)
            self.continue_button.clicked.connect(self.process)
        '''


    def process(self):
        map(run, self.measurements)
        self.continue_button.setText('Done!')
        self.continue_button.clicked.disconnect()
        self.continue_button.clicked.connect(QApplication.instance().quit)

def run(measurement):
    measurement.create_all_psa()
    measurement.create_sbe_batch_file()
    measurement.run_batch()


app = QApplication([])
window = Window()
window.show()
sys.exit(app.exec())




