# zap.spec
block_cipher = None

a = Analysis(
    ['zap.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('lnaddress2invoice.py', '.'),
    ],
    hiddenimports=[
        'PIL.Image',
        'PIL.ImageQt',
        'qrcode',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='zap',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='zap',
)
