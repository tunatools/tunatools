import sharktools
import pathlib

for file in pathlib.Path('data', 'raw').glob('*.hex'):
    sm = sharktools.SHARKTOOLS_Measurement(file, source_folder=file.parent)

    # process all files in folder data\raw with all Seabird functions
    sm.just_do_stuff()

    # copy processed files in a new folder structure for SHARKtools (naming convention and folder tree)
    sm.rename()


    # run specific SBE functions
    # with sm.create_xxx_psa()