from __future__ import print_function

import argparse
import os
import sys
import pprint
import tempfile
import zlib

import imp
from xdis import magics
from xdis import load as xdis_load
import xdis
import xdis.unmarshal
import shutil
import multiprocessing

from PyInstaller.loader import pyimod02_archive
from PyInstaller.archive.readers import CArchiveReader, NotAnArchiveError
import PyInstaller.log


def main(name, pyver='35', outputdir=None, multiproc=False, pyc_persist=True, **unused_options):
    if not os.path.isfile(name):
        print(name, "is an invalid file name!")
        return 1

    arch = get_archive(name)
    show(name, arch)
    if not outputdir:
        outputdir = name.split('.', 1)[0] + '-pyi'
    tmp_outputdir = outputdir + '-tmp'
    # unarchive
    unarchive_pyi(arch, tmp_outputdir, pyver)
    normalize_package_import(tmp_outputdir)

    # uncompyle
    uncompyle_dir(tmp_outputdir, outputdir, pyc_persist, multiproc)


def normalize_package_import(outputdir):
    for root, dirs, files in os.walk(outputdir):
        for x in files:
            basename = os.path.splitext(os.path.basename(x))[0]
            file = os.path.join(root, x)
            pkg_path = os.path.join(root, basename)
            if basename in dirs:
                shutil.move(file, os.path.join(pkg_path, '__init__.pyc'))
    for root, dirs, files in os.walk(outputdir):
        for dir in dirs:
            dir = os.path.join(root, dir)
            pkg_file1 = os.path.join(dir, '__init__.pyc')
            pkg_file2 = os.path.join(dir, '__init__.py')
            if os.path.exists(pkg_file1) or os.path.exists(pkg_file2):
                continue
            open(pkg_file2, 'w').write('')
    print('Normalize_package_import: ok! ')


def uncompyle_dir(srcdir, outputdir, pyc_persist, multiproc):
    if outputdir and not os.path.exists(outputdir):
        os.makedirs(outputdir)
    num_core = multiprocessing.cpu_count() if multiproc else 1
    exe = os.path.join(os.path.split(sys.executable)[0], 'Scripts\\uncompyle6.exe')
    if not os.path.exists(exe):
        exe = 'uncompyle6.exe'
    cmd = [exe, '-r', '-p', str(num_core), '-o', outputdir, srcdir]
    cmd = " ".join(cmd)
    print(cmd)
    rc = os.system(cmd)
    if not rc and not pyc_persist:
        shutil.rmtree(srcdir)


def unarchive_pyc(name, arch, outputdir, magic_int, type=None):
    std_lib_pathes = [os.path.join(os.path.split(sys.executable)[0], x) for x in ('Lib', 'Lib/site-packages')]
    if name.startswith("future.") or name.startswith("__"):
        return
    data = get_data(name, arch)
    # data = asm_typecode(data, pyver, magic_int)
    if type is None:
        name1 = name.replace(".", "/") + ".pyc"
    elif type not in ('x', 'b'):
        # data = asm_typecode(data, pyver, magic_int)
        name1 = name.replace(".", "/") + ".pyc"
    else:
        name1 = name

    tmp_fpath = os.path.join(outputdir, name + '.pyc')
    dst_fpath = os.path.join(outputdir, name1)
    if data[0] & 0x7f == ord('c'):
        open(tmp_fpath, 'wb').write(data)
        is_std = False
        try:
            co = xdis.unmarshal.load_code(open(tmp_fpath, 'rb'), magic_int)
        except Exception as e:
            sys.stdout.write("xdis.unmarshal.load_code error: %s %s\n" % (name1, e))
            is_std = True  # FIXME
        else:
            print('\t', co.co_filename, name1)
            if 'site-packages' in co.co_filename:
                is_std = True
            if not is_std:
                for bs in std_lib_pathes:
                    if os.path.exists(os.path.join(bs, name1[:-1])):
                        is_std = True
                        break
                    if os.path.exists(os.path.join(bs, name1[:-4])):
                        is_std = True
                        break
            if not is_std:
                directory, _ = os.path.split(dst_fpath)
                if directory and not os.path.exists(directory):
                    os.makedirs(directory)
                xdis_load.write_bytecode_file(dst_fpath, co, magic_int, len(data))
        finally:
            if is_std:
                os.remove(tmp_fpath)
            else:
                if tmp_fpath != dst_fpath:
                    os.remove(tmp_fpath)
    else:
        print('ERROR file format: %s', name)


def unarchive_pyi(arch, outputdir, pyver):
    if not arch:
        return
    # pyinstaller/bootloader/pyi_archive.h
    # /* Types of CArchive items. */
    # define ARCHIVE_ITEM_BINARY           'b'  /* binary */
    # define ARCHIVE_ITEM_DEPENDENCY       'd'  /* runtime option */
    # define ARCHIVE_ITEM_PYZ              'z'  /* zlib (pyz) - frozen Python code */
    # define ARCHIVE_ITEM_ZIPFILE          'Z'  /* zlib (pyz) - frozen Python code */
    # define ARCHIVE_ITEM_PYPACKAGE        'M'  /* Python package (__init__.py) */
    # define ARCHIVE_ITEM_PYMODULE         'm'  /* Python module */
    # define ARCHIVE_ITEM_PYSOURCE         's'  /* Python script (v3) */
    # define ARCHIVE_ITEM_DATA             'x'  /* data */
    # define ARCHIVE_ITEM_RUNTIME_OPTION   'o'  /* runtime option */
    magic_int = magics.magic2int(imp.get_magic())
    if isinstance(arch.toc, dict):
        print(" Name: (ispkg, pos, len)")
        show("", arch)
        for name, _ in arch.toc.items():
            unarchive_pyc(name, arch, outputdir, magic_int)
    else:
        print(" pos, length, uncompressed, iscompressed, type, name")
        if outputdir and not os.path.exists(outputdir):
            os.makedirs(outputdir)
        for pos, length, uncompressed, iscompressed, type, name in arch.toc.data:
            if name.startswith('pyimod0') or name.startswith('pyi_rth_'):
                continue
            if type in ('z', 'Z', 'a'):
                data = get_data(name, arch)
                dst_fpath = os.path.join(outputdir, name)
                directory, _ = os.path.split(dst_fpath)
                if directory and not os.path.exists(directory):
                    os.makedirs(directory)
                # open(dst_fpath, 'wb').write(data)
                _arch = get_archive(name, parent=arch)
                unarchive_pyi(_arch, outputdir, pyver)
            else:
                unarchive_pyc(name, arch, outputdir, magic_int, type=type)


def get_archive(name, parent=None):
    if not parent:
        if name[-4:].lower() == '.pyz':
            return ZlibArchive(name)
        return CArchiveReader(name)
    try:
        return parent.openEmbedded(name)
    except KeyError:
        return None
    except (ValueError, RuntimeError):
        ndx = parent.toc.find(name)
        dpos, dlen, ulen, flag, typcd, name = parent.toc[ndx]
        x, data = parent.extract(ndx)
        tempfilename = tempfile.mktemp()
        open(tempfilename, 'wb').write(data)
        if typcd == 'z':
            return ZlibArchive(tempfilename)
        else:
            return CArchiveReader(tempfilename)


def get_data(name, arch):
    if isinstance(arch.toc, dict):
        (ispkg, pos, length) = arch.toc.get(name, (0, None, 0))
        if pos is None:
            return None
        with arch.lib:
            arch.lib.seek(arch.start + pos)
            return zlib.decompress(arch.lib.read(length))
    ndx = arch.toc.find(name)
    dpos, dlen, ulen, flag, typcd, name = arch.toc[ndx]
    x, data = arch.extract(ndx)
    return data


def show(name, arch):
    if isinstance(arch.toc, dict):
        print(" Name: (ispkg, pos, len)")
        toc = arch.toc
    else:
        print(" pos, length, uncompressed, iscompressed, type, name")
        toc = arch.toc.data
    pprint.pprint(toc)


class ZlibArchive(pyimod02_archive.ZlibArchiveReader):
    def checkmagic(self):
        """ Overridable.
            Check to see if the file object self.lib actually has a file
            we understand.
        """
        self.lib.seek(self.start)  # default - magic is at start of file.
        if self.lib.read(len(self.MAGIC)) != self.MAGIC:
            raise RuntimeError("%s is not a valid %s archive file"
                               % (self.path, self.__class__.__name__))
        if self.lib.read(len(self.pymagic)) != self.pymagic:
            print("Warning: pyz is from a different Python version")
        self.lib.read(4)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--persist-pyc',
                        default=True,
                        action="store_true",
                        dest='pyc_persist',
                        help='Keep the .pyc file')
    parser.add_argument('-o', '--outputdir',
                        action='store',
                        default=None,
                        dest='outputdir',
                        help='output directory')
    parser.add_argument('-s', '--multiproc',
                        default=False,
                        action="store_true",
                        dest='multiproc',
                        help='multiprocess')
    parser.add_argument('-v', '--pyver',
                        default="35",
                        action="store",
                        dest='pyver',
                        help='python version: %s' % ",".join(sorted(list(magics.python_versions))))
    PyInstaller.log.__add_options(parser)
    parser.add_argument('name', metavar='pyi_archive',
                        help="pyinstaller archive to show content of")

    args = parser.parse_args()
    PyInstaller.log.__process_options(parser, args)

    try:
        raise SystemExit(main(**vars(args)))
    except KeyboardInterrupt:
        raise SystemExit("Aborted by user request.")


if __name__ == '__main__':
    run()
