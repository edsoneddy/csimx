import glob

from setuptools import setup, find_packages
from setuptools.dist import Distribution

# Compiled parsers are platform-specific. Without this, setuptools would tag the
# wheel "py3-none-any" and PyPI would serve a macOS .dylib to Linux installs,
# where it silently fails to load and csimx falls back to the Python parser with
# no speedup and no error. Marking the distribution impure forces a platform tag
# so each wheel only installs where its binaries actually run.
_HAS_NATIVE_LIBS = bool(
    glob.glob("csimx/native/lib/*.so")
    + glob.glob("csimx/native/lib/*.dylib")
    + glob.glob("csimx/native/lib/*.dll")
)


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return _HAS_NATIVE_LIBS

    def is_pure(self):
        return not _HAS_NATIVE_LIBS


# The parsers are loaded through ctypes and use no CPython API, so they work on
# any Python 3. Left alone, setuptools would tag an impure wheel for the exact
# interpreter that built it (cp314-cp314), and every other Python version would
# fall back to an sdist with no binaries.
_cmdclass = {}
try:
    from wheel.bdist_wheel import bdist_wheel as _bdist_wheel

    class bdist_wheel(_bdist_wheel):
        def finalize_options(self):
            super().finalize_options()
            if _HAS_NATIVE_LIBS:
                self.root_is_pure = False

        def get_tag(self):
            python, abi, platform = super().get_tag()
            if _HAS_NATIVE_LIBS:
                python, abi = "py3", "none"
            return python, abi, platform

    _cmdclass["bdist_wheel"] = bdist_wheel
except ImportError:
    pass  # `wheel` absent: sdist-only build, nothing to retag.

setup(
    name="csimx",
    version="0.1.0",
    packages=find_packages(),
    package_data={
        # Compiled native parsers, when built (scripts/build_native_parsers.sh).
        # Absent builds are fine: csimx falls back to the pure-Python parsers.
        "csimx": ["native/lib/*.so", "native/lib/*.dylib", "native/lib/*.dll"],
        # ANTLR's generated `<Lang>Lexer.tokens` file (one per language
        # package, e.g. csimx/java_20/Java20Lexer.tokens) is the only reliable
        # source for token-type -> literal-text mapping: the generated Lexer
        # class's own `literalNames` list is populated in literal-declaration
        # order, not by token type, so csimx/native/loader.py's
        # _literal_names() reads the .tokens file directly instead (see its
        # docstring). Without this, wheels built before this entry existed
        # silently shipped without any .tokens files at all -- setuptools
        # only includes .py files from packages by default -- and every
        # native-language `csimx tree --show-raw` terminal came back as "".
        "": ["*.tokens"],
    },
    distclass=BinaryDistribution,
    cmdclass=_cmdclass,
    install_requires=[
        "antlr4-python3-runtime==4.13.2",
        "zss==1.2.0",
        "numpy==1.26.4",
        "apted==1.0.3",
        "pygments>=2.20,<3",
    ],
    author="Eddy Lecoña",
    author_email="crew0eddy@gmail.com",
    description="csimx: code similarity in two stages, a fast lexical filter and a structural comparison (parse trees and tree edit distance)",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="https://github.com/EdsonEddy/csimx",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
    ],
    keywords="code analysis, similarity detection, tree parser, tree edit distance, code snippets, code comparison",
    project_urls={
        "Bug Tracker": "https://github.com/EdsonEddy/csimx/issues",
        "Documentation": "https://github.com/EdsonEddy/csimx/wiki",
        "Source Code": "https://github.com/EdsonEddy/csimx",
    },
    python_requires='>=3.10',
    platforms=["All"],
    entry_points={
        'console_scripts': [
            'csimx=csimx.main:main',
        ],
    },
    license="MIT",
)
