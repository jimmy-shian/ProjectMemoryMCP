"""Tree-sitter query templates for extracting code entities across languages."""

# Query strings for each language and entity type
QUERIES = {
    "python": {
        "functions": """
            (function_definition
                name: (identifier) @function.name
                parameters: (parameters) @function.params
                return_type: (type)? @function.return_type
                body: (block) @function.body
            ) @function.def
        """,
        "async_functions": """
            (async_function_definition
                name: (identifier) @function.name
                parameters: (parameters) @function.params
                return_type: (type)? @function.return_type
                body: (block) @function.body
            ) @function.def
        """,
        "classes": """
            (class_definition
                name: (identifier) @class.name
                superclasses: (argument_list)? @class.superclasses
                body: (block) @class.body
            ) @class.def
        """,
        "variables": """
            (assignment
                left: (identifier) @variable.name
                right: (_) @variable.value
            ) @variable.assign

            (annotated_assignment
                left: (identifier) @variable.name
                type: (_) @variable.type
                right: (_)? @variable.value
            ) @variable.annotated
        """,
        "imports": """
            (import_statement
                name: (dotted_name) @import.module
            ) @import.stmt

            (import_from_statement
                module_name: (dotted_name)? @import.from_module
                name: (dotted_name) @import.name
            ) @import.from_stmt
        """,
        "calls": """
            (call
                function: (identifier) @call.func_name
                arguments: (argument_list) @call.args
            ) @call.expr

            (call
                function: (attribute
                    object: (_) @call.object
                    attribute: (identifier) @call.method_name
                )
                arguments: (argument_list) @call.args
            ) @call.method
        """,
        "docstrings": """
            (expression_statement
                (string) @docstring
                (#match? @docstring "^(\"\"\")|('''")
            )
        """,
        "comments": """
            (comment) @comment
        """,
        "decorators": """
            (decorator
                (identifier) @decorator.name
                (call)? @decorator.call
            ) @decorator.def
        """,
        "type_aliases": """
            (type_alias
                name: (identifier) @alias.name
                value: (_) @alias.value
            ) @alias.def
        """,
    },

    "javascript": {
        "functions": """
            (function_declaration
                name: (identifier) @function.name
                parameters: (formal_parameters) @function.params
                body: (statement_block) @function.body
            ) @function.def

            (arrow_function
                parameters: (formal_parameters) @function.params
                body: (_) @function.body
            ) @function.arrow

            (function_expression
                name: (identifier)? @function.name
                parameters: (formal_parameters) @function.params
                body: (statement_block) @function.body
            ) @function.expr
        """,
        "classes": """
            (class_declaration
                name: (identifier) @class.name
                superclass: (class_heritage)? @class.superclass
                body: (class_body) @class.body
            ) @class.def
        """,
        "variables": """
            (variable_declarator
                name: (identifier) @variable.name
                value: (_)? @variable.value
            ) @variable.decl

            (lexical_declaration
                declarators: (variable_declarator
                    name: (identifier) @variable.name
                    value: (_)? @variable.value
                )+
            ) @variable.lexical
        """,
        "imports": """
            (import_statement
                source: (string) @import.source
                import_clause: (import_clause)? @import.clause
                named_imports: (named_imports)? @import.named
            ) @import.stmt

            (import_specifier
                name: (identifier) @import.name
                alias: (identifier)? @import.alias
            ) @import.specifier
        """,
        "calls": """
            (call_expression
                function: (identifier) @call.func_name
                arguments: (arguments) @call.args
            ) @call.expr

            (call_expression
                function: (member_expression
                    object: (_) @call.object
                    property: (property_identifier) @call.method_name
                )
                arguments: (arguments) @call.args
            ) @call.method
        """,
        "comments": """
            (comment) @comment
        """,
    },

    "typescript": {
        "functions": """
            (function_declaration
                name: (identifier) @function.name
                type_parameters: (type_parameters)? @function.type_params
                parameters: (formal_parameters) @function.params
                return_type: (type_annotation)? @function.return_type
                body: (statement_block) @function.body
            ) @function.def

            (method_definition
                name: (property_identifier) @function.name
                type_parameters: (type_parameters)? @function.type_params
                parameters: (formal_parameters) @function.params
                return_type: (type_annotation)? @function.return_type
                body: (statement_block) @function.body
            ) @function.method
        """,
        "classes": """
            (class_declaration
                name: (identifier) @class.name
                type_parameters: (type_parameters)? @class.type_params
                superclass: (class_heritage)? @class.superclass
                body: (class_body) @class.body
            ) @class.def

            (interface_declaration
                name: (identifier) @class.name
                type_parameters: (type_parameters)? @class.type_params
                extends: (extends_clause)? @class.extends
                body: (interface_body) @class.body
            ) @interface.def
        """,
        "variables": """
            (variable_declarator
                name: (identifier) @variable.name
                type: (type_annotation)? @variable.type
                value: (_)? @variable.value
            ) @variable.decl
        """,
        "imports": """
            (import_statement
                source: (string) @import.source
                import_clause: (import_clause)? @import.clause
                named_imports: (named_imports)? @import.named
            ) @import.stmt

            (import_specifier
                name: (identifier) @import.name
                alias: (identifier)? @import.alias
            ) @import.specifier
        """,
        "calls": """
            (call_expression
                function: (identifier) @call.func_name
                type_arguments: (type_arguments)? @call.type_args
                arguments: (arguments) @call.args
            ) @call.expr

            (call_expression
                function: (member_expression
                    object: (_) @call.object
                    property: (property_identifier) @call.method_name
                )
                type_arguments: (type_arguments)? @call.type_args
                arguments: (arguments) @call.args
            ) @call.method
        """,
        "comments": """
            (comment) @comment
        """,
    },

    "rust": {
        "functions": """
            (function_item
                name: (identifier) @function.name
                generics: (generic_parameters)? @function.generics
                parameters: (parameters) @function.params
                return_type: (type)? @function.return_type
                body: (block) @function.body
            ) @function.def
        """,
        "structs": """
            (struct_item
                name: (type_identifier) @struct.name
                generics: (generic_parameters)? @struct.generics
                body: (field_declaration_list) @struct.body
            ) @struct.def
        """,
        "enums": """
            (enum_item
                name: (type_identifier) @enum.name
                generics: (generic_parameters)? @enum.generics
                body: (enum_variant_list) @enum.body
            ) @enum.def
        """,
        "impls": """
            (impl_item
                type: (type_identifier) @impl.type
                generics: (generic_parameters)? @impl.generics
                trait: (type_identifier)? @impl.trait
                body: (associated_item_list) @impl.body
            ) @impl.def
        """,
        "variables": """
            (let_declaration
                pattern: (identifier) @variable.name
                type: (type)? @variable.type
                value: (_)? @variable.value
            ) @variable.let

            (const_item
                name: (identifier) @variable.name
                type: (type) @variable.type
                value: (_) @variable.value
            ) @variable.const
        """,
        "imports": """
            (use_declaration
                argument: (use_tree) @import.tree
            ) @import.stmt

            (use_tree
                path: (scoped_identifier) @import.path
                list: (use_list)? @import.list
            ) @import.tree_node
        """,
        "calls": """
            (call_expression
                function: (identifier) @call.func_name
                arguments: (arguments) @call.args
            ) @call.expr

            (call_expression
                function: (field_expression
                    argument: (_) @call.object
                    field: (field_identifier) @call.method_name
                )
                arguments: (arguments) @call.args
            ) @call.method
        """,
        "comments": """
            (line_comment) @comment
            (block_comment) @comment
        """,
    },

    "go": {
        "functions": """
            (function_declaration
                name: (identifier) @function.name
                parameters: (parameter_list) @function.params
                result: (parameter_list)? @function.results
                body: (block) @function.body
            ) @function.def

            (method_declaration
                receiver: (parameter_list) @function.receiver
                name: (identifier) @function.name
                parameters: (parameter_list) @function.params
                result: (parameter_list)? @function.results
                body: (block) @function.body
            ) @function.method
        """,
        "structs": """
            (type_declaration
                spec: (type_spec
                    name: (type_identifier) @struct.name
                    type: (struct_type) @struct.body
                )
            ) @struct.def
        """,
        "interfaces": """
            (type_declaration
                spec: (type_spec
                    name: (type_identifier) @interface.name
                    type: (interface_type) @interface.body
                )
            ) @interface.def
        """,
        "variables": """
            (var_declaration
                spec: (var_spec
                    name: (identifier) @variable.name
                    type: (type_identifier)? @variable.type
                    value: (_)? @variable.value
                )
            ) @variable.decl

            (short_var_declaration
                left: (identifier) @variable.name
                right: (_) @variable.value
            ) @variable.short
        """,
        "imports": """
            (import_declaration
                spec: (import_spec
                    path: (interpreted_string_literal) @import.path
                    name: (identifier)? @import.name
                )
            ) @import.stmt

            (import_declaration
                spec: (import_spec_list
                    (import_spec
                        path: (interpreted_string_literal) @import.path
                        name: (identifier)? @import.name
                    )+
                )
            ) @import.group
        """,
        "calls": """
            (call_expression
                function: (identifier) @call.func_name
                arguments: (argument_list) @call.args
            ) @call.expr

            (call_expression
                function: (selector_expression
                    operand: (_) @call.object
                    field: (field_identifier) @call.method_name
                )
                arguments: (argument_list) @call.args
            ) @call.method
        """,
        "comments": """
            (comment) @comment
        """,
    },

    "java": {
        "methods": """
            (method_declaration
                name: (identifier) @method.name
                type_parameters: (type_parameters)? @method.type_params
                parameters: (formal_parameters) @method.params
                return_type: (_)? @method.return_type
                body: (block)? @method.body
            ) @method.def
        """,
        "classes": """
            (class_declaration
                name: (identifier) @class.name
                type_parameters: (type_parameters)? @class.type_params
                superclass: (superclass)? @class.superclass
                superinterfaces: (superinterfaces)? @class.interfaces
                body: (class_body) @class.body
            ) @class.def

            (interface_declaration
                name: (identifier) @interface.name
                type_parameters: (type_parameters)? @interface.type_params
                extends: (extends_interfaces)? @interface.extends
                body: (interface_body) @interface.body
            ) @interface.def
        """,
        "variables": """
            (variable_declarator
                name: (identifier) @variable.name
                type: (type_identifier)? @variable.type
                value: (_)? @variable.value
            ) @variable.decl
        """,
        "imports": """
            (import_declaration
                name: (scoped_identifier) @import.name
            ) @import.stmt
        """,
        "calls": """
            (method_invocation
                name: (identifier) @call.method_name
                arguments: (argument_list) @call.args
            ) @call.method

            (method_invocation
                object: (_) @call.object
                name: (identifier) @call.method_name
                arguments: (argument_list) @call.args
            ) @call.object_method
        """,
        "comments": """
            (line_comment) @comment
            (block_comment) @comment
        """,
    },

    "c": {
        "functions": """
            (function_definition
                declarator: (function_declarator
                    declarator: (identifier) @function.name
                    parameters: (parameter_list) @function.params
                )
                type: (_) @function.return_type
                body: (compound_statement) @function.body
            ) @function.def
        """,
        "structs": """
            (struct_specifier
                name: (type_identifier) @struct.name
                body: (field_declaration_list) @struct.body
            ) @struct.def
        """,
        "variables": """
            (declaration
                declarator: (init_declarator
                    declarator: (identifier) @variable.name
                    value: (_)? @variable.value
                )
            ) @variable.decl
        """,
        "imports": """
            (preproc_include
                path: (string_literal) @include.path
            ) @include.stmt
        """,
        "calls": """
            (call_expression
                function: (identifier) @call.func_name
                arguments: (argument_list) @call.args
            ) @call.expr
        """,
        "comments": """
            (comment) @comment
        """,
    },

    "cpp": {
        "functions": """
            (function_definition
                declarator: (function_declarator
                    declarator: (identifier) @function.name
                    parameters: (parameter_list) @function.params
                )
                type: (_)? @function.return_type
                body: (compound_statement) @function.body
            ) @function.def
        """,
        "classes": """
            (class_specifier
                name: (type_identifier) @class.name
                base_class_clause: (base_class_clause)? @class.bases
                body: (field_declaration_list) @class.body
            ) @class.def
        """,
        "variables": """
            (declaration
                declarator: (init_declarator
                    declarator: (identifier) @variable.name
                    value: (_)? @variable.value
                )
            ) @variable.decl
        """,
        "imports": """
            (preproc_include
                path: (string_literal) @include.path
            ) @include.stmt

            (using_declaration
                name: (qualified_identifier) @using.name
            ) @using.decl
        """,
        "calls": """
            (call_expression
                function: (identifier) @call.func_name
                arguments: (argument_list) @call.args
            ) @call.expr

            (call_expression
                function: (field_expression
                    argument: (_) @call.object
                    field: (field_identifier) @call.method_name
                )
                arguments: (argument_list) @call.args
            ) @call.method
        """,
        "comments": """
            (comment) @comment
        """,
    },
}


def get_query(language: str, query_type: str) -> str:
    """
    Get a tree-sitter query for the given language and query type.

    Args:
        language: Language name (python, javascript, typescript, rust, go, java, c, cpp)
        query_type: Query type (functions, classes, variables, imports, calls, comments, etc.)

    Returns:
        Query string or empty string if not found
    """
    lang_queries = QUERIES.get(language, {})
    return lang_queries.get(query_type, "")


def get_all_queries_for_language(language: str) -> dict:
    """Get all available queries for a language."""
    return QUERIES.get(language, {})


def get_supported_query_types(language: str) -> list[str]:
    """Get list of supported query types for a language."""
    return list(QUERIES.get(language, {}).keys())


# Special queries for equation detection
EQUATION_QUERIES = {
    "python": """
        ; Mathematical expressions and assignments that look like equations
        (assignment
            left: (identifier) @eq.var
            right: [
                (binary_operator) @eq.binary
                (call) @eq.call
                (subscript) @eq.subscript
                (attribute) @eq.attribute
            ] @eq.expr
        ) @equation.assign

        ; Augmented assignments (common in iterative algorithms)
        (augmented_assignment
            left: (identifier) @eq.var
            right: (_) @eq.expr
        ) @equation.augmented

        ; Decorators that might indicate equations (e.g., @jit, @torch.jit.script)
        (decorator
            (call
                function: [
                    (attribute
                        attribute: (identifier) @dec.name
                    )
                    (identifier) @dec.name
                ]
            )
        ) @equation.decorator
    """,
}


def get_equation_query(language: str) -> str:
    """Get equation detection query for a language."""
    return EQUATION_QUERIES.get(language, "")
