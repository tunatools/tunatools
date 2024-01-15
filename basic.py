import tunatools
import pathlib

for file in pathlib.Path('data', 'raw').glob('*.hex'):
    sm = tunatools.SHARKTOOLS_Measurement(file, source_folder=file.parent)
    # process all files in folder data\raw with all Seabird functions
    # and copy processed files in a new folder structure for SHARKtools (naming convention and folder tree)
    sm.just_do_stuff()

    # run specific SBE functions with
    # sm.create_xxx_psa()
