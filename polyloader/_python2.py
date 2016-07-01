import io
import os
import os.path
import sys
import imp
import types
import pkgutil


class PolyLoader():
    _loader_handlers = []
    _installed = False

    def __init__(self, fullname, path, is_pkg):
        self.fullname = fullname
        self.path = path
        self.is_package = is_pkg

    @classmethod
    def _install(cls, compiler, suffixes):
        if isinstance(suffixes, basestring):
            suffixes = [suffixes]
        suffixes = set(suffixes)
        overlap = suffixes.intersection(set([suf[0] for suf in imp.get_suffixes()]))
        if overlap:
            raise RuntimeError("Override of native Python extensions is not permitted.")
        overlap = suffixes.intersection(
            set([suffix for (_, suffix) in cls._loader_handlers]))
        if overlap:
            # Fail silently
            return
        cls._loader_handlers += [(compiler, suf) for suf in suffixes]

    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]

        if fullname != self.fullname:
            raise ImportError("Load confusion: %s vs %s." % (fullname, self.fullname))

        matches = [(compiler, suffix) for (compiler, suffix) in self._loader_handlers
                   if self.path.endswith(suffix)]

        if len(matches) == 0:
            raise ImportError("%s is not a recognized module?" % fullname)

        if len(matches) > 1:
            raise ImportError("Multiple possible resolutions for %s: %s" % (
                fullname, ', '.join([suffix for (compiler, suffix) in matches])))

        compiler = matches[0][0]
        with io.FileIO(self.path, 'r') as file:
            source_text = file.read()

        code = compiler(source_text, self.path, fullname)

        module = types.ModuleType(fullname)
        module.__file__ = self.path
        module.__name__ = fullname
        module.__package__ = '.'.join(fullname.split('.')[:-1])

        if self.is_package:
            module.__path__ = [os.path.dirname(module.__file__)]
            module.__package__ = fullname

        exec(code, module.__dict__)
        sys.modules[fullname] = module
        return module


# PolyFinder is an implementation of the Finder class from Python 2.7,
# with embellishments gleefully copied from Python 3.4.  It supports
# all the same functionality for non-.py sourcefiles with the added
# benefit of falling back to Python's default behavior.

# Polyfinder is instantiated by _polyloader_pathhook()

class PolyFinder(object):
    def __init__(self, path=None):
        self.path = path or '.'

    def _pl_find_on_path(self, fullname, path=None):
        subname = fullname.split(".")[-1]
        if self.path is None and subname != fullname:
            return None

        path = os.path.realpath(self.path)
        fls = [("%s/__init__.%s", True), ("%s.%s", False)]
        for (fp, ispkg) in fls:
            for (compiler, suffix) in PolyLoader._loader_handlers:
                composed_path = fp % ("%s/%s" % (path, subname), suffix)
                if os.path.isdir(composed_path):
                    raise IOError("Invalid: Directory name ends in recognized suffix")
                if os.path.isfile(composed_path):
                    return PolyLoader(fullname, composed_path, ispkg)

        # Fall back onto Python's own methods.
        try:
            file, filename, etc = imp.find_module(subname, [path])
        except ImportError as e:
            return None
        return pkgutil.ImpLoader(fullname, file, filename, etc)

    def find_module(self, fullname, path=None):
        return self._pl_find_on_path(fullname)

    @staticmethod
    def getmodulename(path):
        filename = os.path.basename(path)
        suffixes = ([(-len(suf[0]), suf[0]) for suf in imp.get_suffixes()] +
                    [(-len(suf[1]), suf[1]) for suf in PolyLoader._loader_handlers])
        suffixes.sort()
        for neglen, suffix in suffixes:
            if filename[neglen:] == suffix:
                return filename[:neglen]
        return None

    def iter_modules(self, prefix=''):
        if self.path is None or not os.path.isdir(self.path):
            return

        yielded = {}

        try:
            filenames = os.listdir(self.path)
        except OSError:
            # ignore unreadable directories like import does
            filenames = []
        filenames.sort()
        for fn in filenames:
            modname = self.getmodulename(fn)
            if modname == '__init__' or modname in yielded:
                continue

            path = os.path.join(self.path, fn)
            ispkg = False

            if not modname and os.path.isdir(path) and '.' not in fn:
                modname = fn
                try:
                    dircontents = os.listdir(path)
                except OSError:
                    # ignore unreadable directories like import does
                    dircontents = []
                for fn in dircontents:
                    subname = self.getmodulename(fn)
                    if subname == '__init__':
                        ispkg = True
                        break
                else:
                    continue    # not a package

            if modname and '.' not in modname:
                yielded[modname] = 1
                yield prefix + modname, ispkg


def _polyloader_pathhook(path):
    if not os.path.isdir(path):
        raise ImportError('Only directories are supported', path=path)
    return PolyFinder(path)


def install(compiler, suffixes):
    if not PolyLoader._installed:
        sys.path_hooks.append(_polyloader_pathhook)
        PolyLoader._installed = True
    PolyLoader._install(compiler, suffixes)


def reset():
    PolyLoader._loader_handlers = []
    PolyLoader._installed = False
