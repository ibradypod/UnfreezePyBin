# encoding: utf-8

import os,sys
import codecs
import multiprocessing

import uncompyle6


def default_handle_decompile(file, pyc_persist=True, **options):
    if os.path.isfile(file) and file.endswith(".pyc"):
        # FIXME: stdout or logging ?
        sys.stdout.write("[ decompile ] %s \n" % file)
        dst_fpath = file[:-1]
        try:
            uncompyle6.decompile_file(file, codecs.open(dst_fpath, 'wb', encoding="utf-8"), **options)
        except Exception as e:
            sys.stdout.write("uncompyle error: %s \n" % e)
        else:
            if not pyc_persist:
                try:
                    os.remove(file)
                except:
                    pass


class ArchiveExtractor(object):

    def __init__(self, fpath, key="", outputdir=None, reader=None, pyc_persist=True, multiproc=True,
                 handle_decompile=default_handle_decompile, **kwargs):
        self.fpath = fpath
        self.key = key
        self.kwargs = kwargs
        self.reader = reader
        self.pyc_persist = pyc_persist
        self.multiproc = multiproc
        self.handle_decompile = handle_decompile

        if not os.path.isfile(fpath):
            raise NameError("< %s > is an invalid file name!" % fpath)
        if outputdir is None:
            outputdir = os.path.splitext(os.path.basename(fpath))[0] + "-unfreeze"
        self.outputdir = os.path.abspath(outputdir)

    def extract(self):
        '''
        maybe override
        '''
        result = self.reader.extract()
        for typed, path, _data in result:
            dst_fpath = os.path.join(self.outputdir, path)
            directory, _ = os.path.split(dst_fpath)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
            open(dst_fpath, 'wb').write(_data)

    def _uncompyle_single_process(self,files):
        for file in files:
            self.handle_decompile(file, self.pyc_persist)

    def _uncompyle_multi_proces(self,files):
        pool = multiprocessing.Pool()
        for file in files:
            pool.apply(self.handle_decompile, args=(file,self.pyc_persist))
        pool.close()
        pool.join()

    def uncompyle(self):
        # list files
        files_full_path = []
        for root, dirs, files in os.walk(self.outputdir):
            files_full_path.extend([os.path.join(root,x) for x in files])
        # decompile
        if not self.multiproc:
            self._uncompyle_single_process(files_full_path)
        else:
            self._uncompyle_multi_proces(files_full_path)
