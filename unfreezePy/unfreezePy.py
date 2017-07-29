# encoding: utf-8

import traceback
import argparse
import sys

from extractor.pyinstaller import PyinstallerExtractor


def get_argparse():
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--single-process', default=True, action="store_false",
                        dest='multiproc', help='single process')
    parser.add_argument('-c', '--clean-pyc', default=True, action="store_false",
                        dest='pyc_persist', help='Keep the .pyc file')
    parser.add_argument('-o', '--outputdir', action='store',
                        dest='outputdir', help='output directory')
    parser.add_argument('fpath', metavar='pyi_archive',
                        help="binary archive to extract content of")
    args = parser.parse_args()
    return args


def run():
    args = get_argparse()
    print (args)
    extrators = dict([
        ("pyinstaller", PyinstallerExtractor)
    ])
    success = False
    for product in extrators:
        extrator_cls = extrators[product]
        try:
            extrator = extrator_cls(**vars(args))
        except Exception as e:
            sys.stdout.write("[input error] : %s \n" % e.message)
            raise SystemError

        try:
            extrator.extract()
        except Exception as e:
            sys.stdout.write("[trying uncompyle failed] : [ %s ] [ %s ] \n" % (product,e.message))
            continue
        else:
            success = True
            sys.stdout.write("[uncompyle success] : [ %s ]\n" % product)
            try:
                extrator.uncompyle()
            except Exception as e:
                sys.stdout.write("[uncompyle error] : %s\n" % e.message)
            break
    if not success:
        sys.stdout.write("uncompyle failed after all testing\n")


if __name__ == '__main__':
    # test
    sys.argv.extend(["bradypod-web"])
    try:
        run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        raise SystemError(traceback.format_exc())
