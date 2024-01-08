import sharktools
import pathlib

for file in pathlib.Path('data', 'raw').glob('*.hex'):
    sm = sharktools.SHARKTOOLS_Measurement(file, source_folder=file.parent)
    sm.just_do_stuff()
    sm.rename()