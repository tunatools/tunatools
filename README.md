# Install Tunatools
```
git clone https://github.com/tunatools/tunatools
python -m venv venv_tunatools
"venv_tunatools/Scripts/activate"
python -m pip install -r requirements.txt
```

# Using tunatools

### Import data
**The following examples will use the .xmlcon, .hex and .bl with the same stem**\
Just with general name
```
sbe = SBE911_Measurement('EL19-IGV01_CTD04')
```

With an absolute path name
```
sbe = SBE911_Measurement(r'C:\[...]\tunatools\data\raw\EL19-IGV01_CTD04')
```


With a path
```
sbe = SBE911_Measurement(Path(r'C:\[...]\tunatools\data\raw\EL19-IGV01_CTD04'))
```

With a file
```
sbe = SBE911_Measurement(r'C:\[...]\tunatools\data\raw\EL19-IGV01_CTD04.xmlcon')
```


**You can explicitly pass the files, this does not search for files, which means that if you want to use the .bl you have to pass it!**
```
sbe2 = SBE911_Measurement([ r'C:\[...]\tunatools\data\raw_2\AOM23-station-04-cast1.hex',
                            r'C:\[...]\tunatools\data\raw_2\AOM23-station-04-cast1.xmlcon'])
```

If they are in the same folder you can even set the source_folder!
```
sbe2 = SBE911_Measurement(['AOM23-station-04-cast1.hex',
                           'AOM23-station-04-cast1.xmlcon'],
                           source_folder=r"C:\[...]\tunatools\data\raw_2")
```

Maybe you prefer passing them as a dict?
```
sbe2 = SBE911_Measurement({'xmlcon': 'AOM23-station-04-cast1.xmlcon',
                           'hex': 'AOM23-station-04-cast1.hex'},
                          source_folder = r"C:\[...]\tunatools\data\raw_2")
```

Or maybe you don't care? These are equivalent
```
sbe3 = SBE911_Measurement('Ryder19-02-CTD1.xmlcon', 'Ryder19-02-CTD1.hex')
sbe3 = SBE911_Measurement('Ryder19-02-CTD1.hex', 'Ryder19-02-CTD1.xmlcon')
```

You can even combine them if you want!
```
sbe4 = SBE911_Measurement(r'C:\[...]\tunatools\data\raw_2\AOM23-station-04-cast1.hex',
                           'Ryder19-02-CTD1.xmlcon')
                           
sbe4 = SBE911_Measurement('AOM23-station-04-cast1.hex',
                          r'C:\[...]\tunatools\data\raw\Ryder19-02-CTD1.xmlcon',
                          source_folder=r"C:\[...]\tunatools\data\raw_2")
```

### Creating PSAs
Create single psa files by running
```
sm = tunatools.SBE911_Measurement('EL19-IGV01_CTD04')
sm.create_datcnv_psa()
```
This automatically appends datcnv to the list of files to be run in the batch.
For comfort the shortcut `sm.create_all_psa()` exists.

Create the batch file to run all created psas by doing
```
sm.create_sbe_batch_file()
sm.run_batch()
```

Creating all the psa files, the batch file and running can also be done with the shortcut:
```
sm.just_do_stuff()
```

### Example script
In this simple example we run all Seabird functions over all the files in a folder
```
import tunatools
import pathlib

folder = pathlib.Path('data', 'raw')

for file in folder.glob('*.hex'):
    sm = tunatools.SHARKTOOLS_Measurement(file, source_folder=file.parent)
    sm.just_do_stuff()
```

