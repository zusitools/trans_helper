import codecs

# Copied and modified from argparse.py
class CodecFileType(object):
    """Factory for creating file object types

    Instances of FileType are typically passed as type= arguments to the
    ArgumentParser add_argument() method.

    Keyword Arguments:
        - mode -- A string indicating how the file is to be opened. Accepts the
            same values as the builtin open() function.
        - bufsize -- The file's desired buffer size. Accepts the same values as
            the builtin open() function.
    """

    def __init__(self, mode='r', codec='UTF-8'):
        self._mode = mode
        self._codec = codec

    def __call__(self, string):
        return codecs.open(string, self._mode, self._codec)

    def __repr__(self):
        args = [self._mode, self._codec]
        args_str = ', '.join([repr(arg) for arg in args if arg is not None])
        return '%s(%s)' % (type(self).__name__, args_str)
