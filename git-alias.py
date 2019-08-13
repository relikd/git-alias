#!/usr/bin/env python3
# coding=utf8
# Iterate over git config file and extract alias help

from argparse import ArgumentParser, FileType
import re
from os import path, linesep as CRLF
from sys import stdout

ARGS = None


def main():
    global ARGS
    parser = ArgumentParser()
    parser.add_argument('FILE', type=FileType('r'),
                        default=path.expanduser('~/.gitconfig'), nargs='?',
                        help='git config file (default: %(default)s)')
    parser.add_argument('-a', '--all', action='store_true',
                        help='include hidden aliases')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='print complex commands (-vv: pretty print)')
    parser.add_argument('-q', '--quiet', action='count', default=0,
                        help='print less information (up to -qqqq | -qqvv)')
    parser.add_argument('--color', action='store_const', const='+',
                        help='force color output', dest='color')
    parser.add_argument('--no-color', action='store_const', const='-',
                        help='disable color output', dest='color')
    ARGS = parser.parse_args()

    colorMap = {'+': True, '-': False, None: stdout.isatty()}
    ARGS.color = colorMap[ARGS.color]
    AliasConfig(ARGS.FILE).parse()
    ARGS.FILE.close()


class AliasConfig(object):
    ''' Parser for git-config files '''

    def __init__(self, file):
        super(AliasConfig, self).__init__()
        self.file = file
        self.dirty = False
        self.state = None
        self.prevLine = None
        self.comments = []

    def parse(self):
        for line in self.file.readlines():
            # A command can be multiline if the line ends with \
            if self.state == 'alias' and self.prevLine:
                line = line.rstrip()
                if line.endswith('\\'):
                    self.prevLine += '\n' + line[:-1]
                else:
                    self.prevLine += '\n' + line
                    self.parseAlias(self.prevLine)
                    self.prevLine = None
                continue
            else:
                line = line.strip()

            # Ignore empty lines
            # But empty comment will insert a blank line
            if len(line) == 0:
                continue

            if self.parseState(line):
                continue
            # Check if we need to include another alias file
            if self.state == 'include':
                self.parseIncludePath(line)
                continue
            # Ignore parsing for groups other than 'alias'
            if self.state != 'alias':
                continue
            # Add comments to internal array
            if self.isComment(line):
                continue
            # not a config group, not a comment ... must be the alias
            if line.endswith('\\'):
                self.prevLine = line[:-1]
            else:
                self.parseAlias(line)

    def parseState(self, line):
        config = re.search(r'^\[(.+)\]$', line)
        if config:
            self.state = config.group(1).strip().lower()
        return config

    def printSection(self, title):
        if ARGS.quiet <= 1:
            print(Format().section(title.strip(';# \t'), self.dirty))
            self.dirty = True

    def isComment(self, line):
        if line[0] not in ';#':
            return False
        # If line starts with ## asume this to be a section title
        noBlanks = line.replace(' ', '')
        if len(noBlanks) > 1 and noBlanks[1] in ';#':
            self.printSection(line)
        else:
            self.comments.append(line[1:].lstrip())
        return True

    def parseAlias(self, line):
        cmd = re.search(r'^(.+?)\s*=\s*([\s\S]+)$', line)
        alias = Alias(cmd.group(1).strip(), cmd.group(2).strip())
        if alias.parse(self.comments):
            print(alias)
        self.comments = []
        self.dirty = True

    def parseIncludePath(self, line):
        param = re.search(r'^(.+?)\s*=\s*([\s\S]+)$', line)
        if param and param.group(1).strip() == 'path':
            path = param.group(2).strip()
            if ARGS.quiet <= 1:  # if 'quiet == 0', copy self.dirty
                print(CRLF + '@include: %s' % path)
            with open(path, 'r') as f:
                AliasConfig(f).parse()
            if ARGS.quiet <= 1:
                print('@end: %s' % path + CRLF)


class Alias(object):
    ''' Object for alias name, command, and helping hints '''

    def __init__(self, name, command):
        super(Alias, self).__init__()
        self.name = name
        self.command = AliasCommand(command)
        self.usage = None
        self.hints = ''
        self.ignore = False

    def __str__(self):
        str = Format().alias(self.name)
        if self.usage and ARGS.quiet <= 3:
            str += ' ' + Format().usage(self.usage)
        if self.command.shouldPrint(self.hints):
            str += self.command.__str__()
        if ARGS.quiet == 0:
            str += self.hints
        if ARGS.verbose >= 1 and ARGS.quiet <= 2:
            str += CRLF
        return str

    def addDescription(self, line):
        self.hints += Format().indent(line)

    def parse(self, commentsList):
        ''' Process list of comments (all comments above alias) '''
        for comment in commentsList:
            x = comment.split(':')
            ctrl = x[0].strip().lower()

            if len(x) < 2 or self.ctrlSequence(ctrl, ':'.join(x[1:]).strip()):
                # Allow user to hide individual comments with '#!#'
                if not comment.startswith('!#'):
                    self.addDescription(comment)

            if self.ignore and not ARGS.all:
                return False
        return True

    def ctrlSequence(self, instruction, tail):
        ''' Parse lines with format `%s: %s` '''
        # Auto-detect urls
        if instruction in ['http', 'https']:
            tail = instruction + ':' + tail
            instruction = 'link'
        # Append usage (in red) to command (ignoring first word)
        if instruction in ['usage', 'use']:
            self.usage = re.sub(r'^%s\s*' % self.name, '', tail, flags=re.I)
        # Print url (in light gray)
        elif instruction in ['see', 'link', 'url', 'web']:
            self.addDescription(Format().link(tail))
        # Some program specific controls
        elif instruction == '!':
            self.lintInstruction(tail.lower())
        else:
            return True
        return False

    def lintInstruction(self, instruction):
        ''' Parse lines with format `!: %s` '''
        for _cmd_ in [x.strip() for x in instruction.split(',')]:
            if _cmd_ == 'ignore':
                self.ignore = True
            elif re.match('^show( command| cmd)?$', _cmd_):
                self.command.show = True
            elif re.match('^hide|(hide|not?) (command|cmd)$', _cmd_):
                self.command.show = False
            elif re.match('^(single ?|in)line$', _cmd_):
                self.command.inline = True
            elif re.match('^(new ?|multi ?|not? (single ?|in))line$', _cmd_):
                self.command.inline = False
            elif re.match('^prett(if)?y', _cmd_):
                self.command.prettify = True


class AliasCommand(object):
    '''
    Very basic bash parser.
    Inserts new line for: ';', '{', '}', ' && ' and ' | '
    Escapes: \"
    '''

    def __init__(self, txt):
        super(AliasCommand, self).__init__()
        self.input = txt
        # linting
        self.inline = len(txt) < 42  # not self.isComplex()
        self.show = None
        self.prettify = False
        # result parsing
        self.skip = 0
        self.indentation = 0
        self.tempIndent = False
        self.newline = False
        self.escapeQuotes = False

    def __str__(self):
        cmd = self.input
        if ARGS.verbose >= 2:
            self.inline = False
        if self.isComplex() and (self.prettify or ARGS.verbose >= 2):
            cmd = self.parse()
        elif ARGS.verbose == 1 and not self.inline:
            cmd = Format().fx([RED, FAINT], cmd)
        return Format().command(cmd, self.inline)

    def shouldPrint(self, hasHints=False):
        if (self.show is False and not ARGS.all) or ARGS.quiet >= 3:
            return False
        # Print complex command only if user added no comment to describe it
        # Otherwise, its most likely too complex to display
        if not self.inline:
            if hasHints and not self.show and ARGS.verbose == 0:
                return False
        return True

    def isComplex(self):
        return self.input.lstrip('"').startswith('!')

    def preprocessInput(self, text):
        if text.startswith('!'):
            text = text[1:].lstrip()
        if text.startswith('"'):
            text = text[1:].lstrip('! \t')
            self.escapeQuotes = True
        return text

    def append(self, char):
        if self.newline and char in ' \t\n\r':
            return
        if self.newline:
            self.newline = False
            self.result += Format().indent(' ' * 4 * self.indentation)
            if self.tempIndent:
                self.result += Format().fx([BLACK, FAINT], '↳  ')
                self.tempIndent = False
        self.result += char

    def parse(self):
        raw = self.preprocessInput(self.input)
        self.result = ''
        for i, char in enumerate(raw):
            if self.skip > 0:
                self.skip -= 1
                continue

            if char == '\\':
                if self.parseCharEscape(raw[i + 1]):
                    continue
            elif char == '$':
                if self.parseBashVariable(raw[i + 1:]):
                    continue
            elif self.escapeQuotes and char == '"':
                self.escapeQuotes = False
                continue
            # Insert new lines after '{', '}', and ';'
            elif char == '}' and raw[i - 1] != '{':
                self.indentation -= 1
                self.newline = True
            self.append(char)
            if char == '{' and raw[i + 1] != '}':
                self.indentation += 1
                self.newline = True
            elif char == ';':
                self.newline = True
            # Insert new line for ' && ' and ' | '
            elif char in '&|':
                self.parseBashPipes(raw[i - 2:i + 2])
        return self.result

    def parseBashPipes(self, text):
        if text == ' && ' or text[1:] == ' | ':
            self.tempIndent = True
            self.newline = True

    def parseBashVariable(self, text):
        c = text[0]
        var = None
        if c in '0123456789!$?#*-@':
            var = c
        elif c in '{':
            match = re.search(r'^.*?[}]', text)
            var = match.group(0)
        else:
            match = re.search(r'^[a-zA-Z_][a-zA-Z_0-9]*', text)
            if match:
                var = match.group(0)
        if var:
            # Highlight input variables
            self.result += Format().inlineVariable('$' + var)
            self.skip = len(var)
        return self.skip > 0

    def parseCharEscape(self, following):
        if self.escapeQuotes and following == '"':
            self.result += following
            self.skip = 1
        return self.skip > 0


class Format(object):
    ''' Abstraction for structuring output '''

    def __init__(self):
        super(Format, self).__init__()

    def section(self, text, newline=True):
        head = self.fx([BLUE, BOLD, UNDERLINE], text, alt='=== %s ===')
        return (CRLF if newline else '') + head

    def alias(self, text):
        if ARGS.quiet >= 2:
            return self.fx([RED, BOLD], text)
        return ' ' + self.fx([RED, BOLD], text, alt='+ %s')

    def usage(self, text):
        return self.fx([RED], text)

    def command(self, text, inline=True):
        return ('  →  ' if inline else self.indent()) + text

    def link(self, text):
        return '@: ' + self.fx([BLACK, FAINT], text)

    def indent(self, text=''):
        return CRLF + '    ' + text

    def inlineVariable(self, text):
        return self.fx([YELLOW, BOLD], text)

    def fx(self, params, text, alt='%s'):
        ''' if --no-color use alternative format '''
        if ARGS.color:
            left = '\x1b[' + ';'.join(params) + 'm'
            right = '\x1b[0m'
            return left + text.replace(right, right + left) + right
        else:
            return alt % text


BLACK = '30'
RED = '31'
GREEN = '32'
YELLOW = '33'
BLUE = '34'
MAGENTA = '35'
CYAN = '36'
WHITE = '37'

BOLD = '01'
FAINT = '02'
ITALIC = '03'
UNDERLINE = '04'
BLINKSLOW = '05'
BLINK = '06'
NEGATIVE = '07'
CONCEALED = '08'


if __name__ == '__main__':
    main()
