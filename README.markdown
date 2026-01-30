# Lightning Address to BOLT11 Invoice Generator

This simple GUI `zap.py` and CLI script `lnaddress2invoice.py` allow you to generate BOLT11 invoices from Lightning Addresses.
It asks for the Lightning Address and desired amount and returns a BOLT11 invoice.

> Hecho con ❤️ y ⚡ en Puerto Rico 🏝️

The script originally was almost completely lifted from https://sendsats.to/.
It's a cool site for using your Lightning Address.

## Usage

You can run the script using Python 3. Make sure you have Python 3 installed on your system.
For convenience there was added a `shell.nix` and a `pyproject.toml` to manage dependencies.

### GUI Usage

To run the GUI, execute `zap.py` on your graphical environment or via CLI with `$ ./zap.py`

### Script Usage

To run the CLI script:

```sh
$ ./lnaddress2invoice.py
```

Optionally you can use the command line arguments as shown by `$ ./lnaddress2invoice.py --help`

### Install as application

#### On NixOS

```
nix build
./result/bin/zap # run
nix profile add ./result # install
~/.nix-profile/bin/zap # run, or select from application menu of your desktop environment
```

#### On other systems with PyInstaller

Untested territory, feedback welcome.

```
pip install -r requirements.txt
pip install pyinstaller
pyinstaller zap.spec
```

## License

This project is free and open source software designed to be stolen.
Please steal this code and make something better, original or fun.

This project is licensed under the terms of the MIT license. For more details, please see the [LICENSE](LICENSE) file.
