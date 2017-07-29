import struct

padding = '\x00\x00\x00\x00'


def __build_magic(magic):
    return struct.pack(b'Hcc', magic, b'\r', b'\n')

# FIXME:  xdis 3.5.1 : xdis/magics.py ?

PYTHON_MAGIC = {
    # version magic numbers (see Python/Lib/importlib/_bootstrap_external.py)
    '15': __build_magic(20121),
    '16': __build_magic(50428),
    '20': __build_magic(50823),
    '21': __build_magic(60202),
    '22': __build_magic(60717),
    '23': __build_magic(62011),
    '24': __build_magic(62061),
    '25': __build_magic(62131),
    '26': __build_magic(62161),
    '27': __build_magic(62191),
    '30': __build_magic(3000),
    '31': __build_magic(3141),
    '32': __build_magic(3160),
    '33': __build_magic(3190),
    '34': __build_magic(3250),
    '35': __build_magic(3350),
    '36': __build_magic(3360),
    '37': __build_magic(3390),
}


def get_magic_string(pyver):
    return PYTHON_MAGIC.get(str(pyver)) + padding

