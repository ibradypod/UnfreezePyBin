# encoding: utf-8

import os
import traceback

from app.pyinstaller.readers import CArchiveReader
from app.pyinstaller.readers import ZlibArchiveReader
from extractor import ArchiveExtractor


class PyinstallerExtractor(ArchiveExtractor):

    def __init__(self, fpath, **kwargs):
        key = kwargs.get("key","")
        reader = ZlibArchiveReader(fpath,key) if fpath.lower().endswith(".pyz") \
            else CArchiveReader(fpath,key)
        super(PyinstallerExtractor, self).__init__(fpath, reader=reader, **kwargs)
