from colorama import init
init(autoreset=True)

import json

# pygments is optional for now
try:
    import pygments
except ImportError:
    got_pygments = False
else:
    got_pygments = True
    from pygments import highlight, util
    from pygments.lexers import get_lexer_by_name
    from pygments.formatters import get_formatter_by_name, get_all_formatters
    from pygments.styles import get_style_by_name, get_all_styles


PRETTY_FORMATTER = 'console256'
PRETTY_STYLE = 'tango'

def pretty(ob, lexer=None):
    """
    Return a pretty console text representation of 'ob'.
    If 'ob' is something else than plain text, specify it in 'lexer'.

    If 'ob' is dict, Json lexer is assumed.

    Command line switches can be used to control highlighting and style.
    """
    if lexer is None and isinstance(ob, dict):
        lexer = 'json'

    if lexer == 'json':
        ob = json.dumps(ob, indent=4, sort_keys=True)

    if got_pygments:
        ret = highlight(
            ob,
            get_lexer_by_name(lexer),
            get_formatter_by_name(PRETTY_FORMATTER, style=PRETTY_STYLE)
        )
    else:
        ret = ob

    return ret


def set_pretty_settings(formatter=None, style=None):
    if not got_pygments:
        return

    global PRETTY_FORMATTER
    global PRETTY_STYLE

    try:
        if formatter:
            get_formatter_by_name(formatter)
            PRETTY_FORMATTER = formatter

        if style:
            get_style_by_name(style)
            PRETTY_STYLE = style

    except util.ClassNotFound as e:
        print "Note: ", e
        print get_avaible_pretty_settings()


def get_avaible_pretty_settings():
    formatters = ', '.join([f.aliases[0] for f in get_all_formatters()])
    styles = ', '.join(list(get_all_styles()))
    s = "Available formatters: {}\nAvailable styles: {}".format(formatters, styles)
    return s
