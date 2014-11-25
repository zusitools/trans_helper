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

    def __init__(self, mode='r', default_codec='UTF-8'):
        self._mode = mode
        self._default_codec = default_codec

    def __call__(self, string):
        filename = string
        codec = self._default_codec
        try:
            (filename, codec) = string.split('@', 1)
        except ValueError:
            pass
        return codecs.open(filename, self._mode, codec)

    def __repr__(self):
        args = [self._mode, self._default_codec]
        args_str = ', '.join([repr(arg) for arg in args if arg is not None])
        return '%s(%s)' % (type(self).__name__, args_str)
