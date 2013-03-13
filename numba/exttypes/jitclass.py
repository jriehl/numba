"""
Compiling @jit extension classes works as follows:

    * Create an extension Numba/minivect type holding a symtab
    * Capture attribute types in the symtab ...

        * ... from the class attributes:

            @jit
            class Foo(object):
                attr = double

        * ... from __init__

            @jit
            class Foo(object):
                def __init__(self, attr):
                    self.attr = double(attr)

    * Type infer all methods
    * Compile all extension methods

        * Process signatures such as @void(double)
        * Infer native attributes through type inference on __init__
        * Path the extension type with a native attributes struct
        * Infer types for all other methods
        * Update the ext_type with a vtab type
        * Compile all methods

    * Create descriptors that wrap the native attributes
    * Create an extension type:

      {
        PyObject_HEAD
        ...
        virtual function table (func **)
        native attributes
      }

    The virtual function table (vtab) is a ctypes structure set as
    attribute of the extension types. Objects have a direct pointer
    for efficiency.
"""

import numba
from numba import error
from numba import typesystem
from numba import pipeline
from numba import symtab
from numba.exttypes.utils import is_numba_class
from numba.minivect import minitypes

from numba.exttypes import logger
from numba.exttypes import virtual
from numba.exttypes import signatures
from numba.exttypes import utils
from numba.exttypes import validators
from numba.exttypes import compileclass
from numba.exttypes import extension_types

from numba.typesystem.exttypes import ordering

#------------------------------------------------------------------------
# Populate Extension Type with Methods
#------------------------------------------------------------------------

class JitExtensionCompiler(compileclass.ExtensionCompiler):
    """
    Compile @jit extension classes.
    """

    method_validators = validators.jit_validators
    exttype_validators = validators.jit_type_validators

    def compile_methods(self):
        for i, method in enumerate(self.methods):
            func_env = self.func_envs[method]
            pipeline.run_env(self.env, func_env, pipeline_name='compile')

            method.lfunc = func_env.lfunc
            method.lfunc_pointer = func_env.translator.lfunc_pointer

            method.wrapper_func = func_env.numba_wrapper_func

#------------------------------------------------------------------------
# Build Attributes Struct
#------------------------------------------------------------------------

class JitAttributeBuilder(compileclass.AttributeBuilder):

    def finalize(self, ext_type):
        ext_type.attribute_table.create_attribute_ordering(ordering.extending)

    def create_descr(self, attr_name):
        """
        Create a descriptor that accesses the attribute on the ctypes struct.
        """
        def _get(self):
            return getattr(self._numba_attrs, attr_name)
        def _set(self, value):
            return setattr(self._numba_attrs, attr_name, value)
        return property(_get, _set)

#------------------------------------------------------------------------
# Build Extension Type
#------------------------------------------------------------------------

def create_extension(env, py_class, flags):
    """
    Compile an extension class given the NumbaEnvironment and the Python
    class that contains the functions that are to be compiled.
    """
    flags.pop('llvm_module', None)

    ext_type = typesystem.JitExtensionType(py_class)

    extension_compiler = JitExtensionCompiler(
        env, py_class, ext_type, flags,
        signatures.JitMethodMaker(ext_type),
        compileclass.AttributesInheriter(),
        JitAttributeBuilder(),
        virtual.StaticVTabBuilder())

    extension_compiler.infer()
    extension_compiler.finalize_tables()
    extension_compiler.validate()
    extension_type = extension_compiler.compile()

    return extension_type
