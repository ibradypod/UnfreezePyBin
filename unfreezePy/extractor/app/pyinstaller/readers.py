# encoding: utf-8

import StringIO
import marshal
import struct
import sys
import zlib

import Crypto.Cipher.AES

from . import utils


def marshal_load(data,pyver):
    pyc = marshal.loads(data)
    fpath = pyc.co_filename #.pyc
    if fpath.endswith(".py"):
        fpath += "c"
    _data = utils.get_magic_string(pyver) + data
    return fpath,_data


class ArchiveReader(object):
    """
    A base class for a repository of python code objects.
    The extract method is used by imputil.ArchiveImporter
    to get code objects by name (fully qualified name), so
    an enduser "import a.b" would become
      extract('a.__init__')
      extract('a.b')
    """
    MAGIC = b'PYL\0'
    HDRLEN = 12  # default is MAGIC followed by python's magic, int pos of toc
    TOCPOS = 8
    os = None
    _bincache = None

    def __init__(self, path=None, start=0, fp=None):
        """
        Initialize an Archive. If path is omitted, it will be an empty Archive.
        """
        self.toc = None
        self.path = path
        self.start = start

        # In Python 3 module 'imp' is no longer built-in and we cannot use it.
        # There is for Python 3 another way how to obtain magic value.
        if sys.version_info[0] == 2:
            import imp
            self.pymagic = imp.get_magic()
        else:
            # We cannot use at this bootstrap stage importlib directly
            # but its frozen variant.
            import _frozen_importlib
            if sys.version_info[1] <= 3:
                # Python 3.3
                self.pymagic = _frozen_importlib._MAGIC_BYTES
            elif sys.version_info[1] == 4:
                # Python 3.4
                self.pymagic = _frozen_importlib.MAGIC_NUMBER
            else:
                # Python 3.5+
                self.pymagic = _frozen_importlib._bootstrap_external.MAGIC_NUMBER
        if fp:
            self.file = fp
        else:
            self.file = open(self.path, 'rb')
        self.checkmagic()
        self.loadtoc()


    @staticmethod
    def toc_read_from_binary(s):
        """
        Decode the binary string into an in memory list.

        S is a binary string.
        """

        # pyinstaller/bootloader/pyi_archive.h
        # /* TOC entry for a CArchive */
        # typedef struct _toc {
        #     int  structlen;  /*len of this one - including full len of name */
        #     int  pos;        /* pos rel to start of concatenation */
        #     int  len;        /* len of the data (compressed) */
        #     int  ulen;       /* len of data (uncompressed) */
        #     char cflag;      /* is it compressed (really a byte) */
        #     char typcd;      /* type code -'b' binary, 'z' zlib, 'm' module,
        #                       * 's' script (v3),'x' data, 'o' runtime option  */
        #     char name[1];    /* the name to save it as */
        #     /* starting in v5, we stretch this out to a mult of 16 */
        # } TOC;
        ENTRYSTRUCT = '!iiiiBB'  # (structlen, dpos, dlen, ulen, flag, typcd) followed by name
        ENTRYLEN = struct.calcsize(ENTRYSTRUCT)
        p = 0
        toc = []
        while p < len(s):
            (slen, dpos, dlen, ulen, flag, typcd) = struct.unpack(ENTRYSTRUCT, s[p:p + ENTRYLEN])
            nmlen = slen - ENTRYLEN
            p = p + ENTRYLEN
            (nm,) = struct.unpack('%is' % nmlen, s[p:p + nmlen])
            p = p + nmlen
            # nm may have up to 15 bytes of padding
            nm = nm.rstrip(b'\0')
            nm = nm.decode('utf-8')
            typcd = chr(typcd)
            toc.append((dpos, dlen, ulen, flag, typcd, nm))
        return toc

    def loadtoc(self):
        """
        Load the table of contents into memory.
        """
        raise NotImplementedError

    def extract(self):
        """
        Get the contents of an entry.
        """
        raise NotImplementedError

    def checkmagic(self):
        """
        Overridable.
        Check to see if the file object self.file actually has a file
        we understand.
        """
        self.file.seek(self.start)  # default - magic is at start of file

        if self.file.read(len(self.MAGIC)) != self.MAGIC:
            raise LookupError("%s is not a valid %s archive file"
                                   % (self.path, self.__class__.__name__))

        if self.file.read(len(self.pymagic)) != self.pymagic:
            raise LookupError("%s has version mismatch to dll" %
                (self.path))


class CArchiveReader(ArchiveReader):
    """
    An Archive subclass that can hold arbitrary data.

    This class encapsulates all files that are bundled within an executable.
    It can contain ZlibArchive (Python .pyc files), dlls, Python C extensions
    and all other data files that are bundled in --onefile mode.
    """
    # MAGIC is usefull to verify that conversion of Python data types
    # to C structure and back works properly.
    MAGIC = b'MEI\014\013\012\013\016'
    HDRLEN = 0
    LEVEL = 9

    # pyinstaller/bootloader/pyi_archive.h
    # Cookie - holds some information for the bootloader. C struct format
    # definition. '!' at the beginning means network byte order.
    # C struct looks like:
    #
    #   typedef struct _cookie {
    #       char magic[8]; /* 'MEI\014\013\012\013\016' */
    #       int  len;      /* len of entire package */
    #       int  TOC;      /* pos (rel to start) of TableOfContents */
    #       int  TOClen;   /* length of TableOfContents */
    #       int  pyvers;   /* new in v4 */
    #       char pylibname[64];    /* Filename of Python dynamic library. */
    #   } COOKIE;
    #
    _cookie_format = '!8siiii64s'
    _cookie_size = struct.calcsize(_cookie_format)

    def __init__(self, archive_path, start=0, length=0, fp=None, pylib_name='', key=""):
        """
        Constructor.

        archive_path path name of file (create empty CArchive if path is None).
        start        is the seekposition within PATH.
        len          is the length of the CArchive (if 0, then read till EOF).
        pylib_name   name of Python DLL which bootloader will use.
        """
        self.length = length
        self.pylib_name = pylib_name
        self.key = key

        # A CArchive created from scratch starts at 0, no leading bootloader.
        self.pkg_start = 0
        super(CArchiveReader, self).__init__(archive_path, start, fp)

    def checkmagic(self):
        """
        Verify that self is a valid CArchive.
        Magic signature is at end of the archive.
        """
        # Magic is at EOF; if we're embedded, we need to figure where that is.
        if self.length:
            self.file.seek(self.start + self.length, 0)
        else:
            self.file.seek(0, 2)
        filelen = self.file.tell()

        self.file.seek(max(0, filelen - 4096))
        searchpos = self.file.tell()
        buf = self.file.read(min(filelen, 4096))
        pos = buf.rfind(self.MAGIC)
        if pos == -1:
            raise RuntimeError("%s is not a valid %s archive file" %
                               (self.path, self.__class__.__name__))
        filelen = searchpos + pos + self._cookie_size
        (magic, totallen, self.tocpos, self.toclen, self.pyvers, pylib_name) = struct.unpack(
            self._cookie_format, buf[pos:pos + self._cookie_size])
        if magic != self.MAGIC:
            raise RuntimeError("%s is not a valid %s archive file" %
                               (self.path, self.__class__.__name__))

        self.pkg_start = filelen - totallen
        if self.length:
            if totallen != self.length or self.pkg_start != self.start:
                raise RuntimeError('Problem with embedded archive in %s' %
                                   self.path)
        if not self.pylib_name:
            self.pylib_name = pylib_name.rstrip(b'\0')
        # Verify presence of Python library name.
        if not self.pylib_name:
            raise RuntimeError('Python library filename not defined in archive.')

    def loadtoc(self):
        self.file.seek(self.pkg_start + self.tocpos)
        tocstr = self.file.read(self.toclen)
        self.toc = self.toc_read_from_binary(tocstr)

    def extract(self):
        result = []
        for dpos, dlen, ulen, flag, typcd, name in self.toc:
            print (dpos, dlen, ulen, flag, typcd, name)
            self.file.seek(self.pkg_start + dpos)
            rslt = self.file.read(dlen)
            if flag == 1:   # compressed
                rslt = zlib.decompress(rslt)
            #
            # xformdict = {'PYMODULE': 'm',
            #              'PYSOURCE': 's',
            #              'EXTENSION': 'b',
            #              'PYZ': 'z',
            #              'PKG': 'a',
            #              'DATA': 'x',
            #              'BINARY': 'b',
            #              'ZIPFILE': 'Z',
            #              'EXECUTABLE': 'b',
            #              'DEPENDENCY': 'd'}
            #
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
            if typcd == 'm':
                result.append((typcd, name, rslt))
            elif typcd == 's':
                _fpath, _data = marshal_load(rslt, self.pyvers)
                result.append((typcd, _fpath, _data))
            elif typcd.lower() == 'z':
                _io = StringIO.StringIO(rslt)
                _io.seek(0)
                zlib_arch = ZlibArchiveReader(name,fp=_io,pyver=self.pyvers,key=self.key)
                result += zlib_arch.extract()
            else:
                result.append((typcd, name, rslt))
        return result


class Cipher(object):
    """
    This class is used only to decrypt Python modules.
    """
    # For decrypting Python modules.
    CRYPT_BLOCK_SIZE = 16

    def __init__(self,key=""):
        # At build-type the key is given to us from inside the spec file, at
        # bootstrap-time, we must look for it ourselves by trying to import
        # the generated 'pyi_crypto_key' module.

        self.has_key = False if key == "" else True

        assert type(key) is str
        if len(key) > self.CRYPT_BLOCK_SIZE:
            self.key = key[0:self.CRYPT_BLOCK_SIZE]
        else:
            self.key = key.zfill(self.CRYPT_BLOCK_SIZE)
        assert len(self.key) == self.CRYPT_BLOCK_SIZE

        self._aes = Crypto.Cipher.AES

    def __create_cipher(self, iv):
        # The 'BlockAlgo' class is stateful, this factory method is used to
        # re-initialize the block cipher class with each call to encrypt() and
        # decrypt().
        return self._aes.new(self.key, self._aes.MODE_CFB, iv)

    def decrypt(self, data):
        return self.__create_cipher(data[:self.CRYPT_BLOCK_SIZE]).decrypt(data[self.CRYPT_BLOCK_SIZE:])


class ZlibArchiveReader(ArchiveReader):
    """
    ZlibArchive - an archive with compressed entries. Archive is read
    from the executable created by PyInstaller.

    This archive is used for bundling python modules inside the executable.

    NOTE: The whole ZlibArchive (PYZ) is compressed so it is not necessary
          to compress single modules with zlib.
    """
    MAGIC = b'PYZ\0'
    TOCPOS = 8
    HDRLEN = ArchiveReader.HDRLEN + 5

    # content types for PYZ
    PYZ_TYPE_MODULE = 0
    PYZ_TYPE_PKG = 1
    PYZ_TYPE_DATA = 2

    def __init__(self, path, offset=None, fp=None, pyver=None, key=""):
        if path is None:
            offset = 0
        elif offset is None:
            for i in range(len(path) - 1, - 1, - 1):
                if path[i] == '?':
                    try:
                        offset = int(path[i + 1:])
                    except ValueError:
                        # Just ignore any spurious "?" in the path
                        # (like in Windows UNC \\?\<path>).
                        continue
                    path = path[:i]
                    break
            else:
                offset = 0
        self.pyver = pyver
        super(ZlibArchiveReader, self).__init__(path, offset, fp)

        self.cipher = Cipher(key)

    def loadtoc(self):
        """
        Overridable.
        Default: After magic comes an int (4 byte native) giving the
        position of the TOC within self.lib.
        Default: The TOC is a marshal-able string.
        """
        self.file.seek(self.start + self.TOCPOS)
        (offset,) = struct.unpack('!i', self.file.read(4))
        self.file.seek(self.start + offset)
        # Use marshal.loads() since load() arg must be a file object
        # Convert the read list into a dict for faster access
        self.toc = dict(marshal.loads(self.file.read()))

    def extract(self):
        data = []
        for name in self.toc:
            typ, pos, length = self.toc[name]
            self.file.seek(self.start + pos)
            obj = self.file.read(length)
            try:
                if self.cipher.has_key:
                    obj = self.cipher.decrypt(obj)
                obj = zlib.decompress(obj)
                if typ in (self.PYZ_TYPE_MODULE, self.PYZ_TYPE_PKG):
                    name,obj = marshal_load(obj,self.pyver)
            except EOFError:
                raise ImportError("PYZ entry '%s' failed to unmarshal" % name)
            print("pyz",typ, pos, length,name)
            data.append((typ, name, obj))
        return data
