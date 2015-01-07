import argparse
import myargparse
import os
import sys
import re
from collections import defaultdict

class TranslationException(Exception):
  def __str__(self):
    return repr(self.args[0])

class TranslationEntry:
  def __init__(self, key, value='', source_value='', context='',
      leftquote='', rightquote='', leftspaces=0, rightspaces=0):
    self.key = key
    self.value = value
    self.source_value = source_value
    self.context = context
    self.leftquote = leftquote
    self.rightquote = rightquote
    self.leftspaces = leftspaces
    self.rightspaces = rightspaces

  def __str__(self):
    return "'%s' [%s] = '%s'" % (self.key, self.context, self.value)

  def __repr__(self):
    return self.__str__()

class TranslationFile:
  def __init__(self):
    # Entries by key. Multiple entries may have the same key
    # (because of errors in the translation file or because of
    # multiple translation files in one po file).
    self.entries = defaultdict(set)
    self.entries_in_order = []

  def __iter__(self):
    return iter(self.entries_in_order)

  def append(self, entry):
    self.entries[entry.key].add(entry)
    self.entries_in_order.append(entry)

  def read_from_zusi(self, f, contexts, strip_shortcuts = False):
    for line in f:
      try:
        (key, value) = line.strip("\r\n").split(" = ", 1)
      except ValueError:
        continue
      leftspaces = len(value) - len(value.lstrip(" "))
      rightspaces = len(value) - len(value.rstrip(" "))
      value = value.strip(" ")
      leftquote = len(value) > 0 and value[0] == "'"
      rightquote = len(value) > 1 and value[-1] == "'"
      value = value.strip("'")
      if strip_shortcuts and ('Caption' in key or 'Text' in key):
        value = re.sub(r'(?<!&)&(?!&)', '', value) # negative lookbehind and lookahead
      try:
        context = contexts[key]
      except KeyError:
        context = ''
      self.append(TranslationEntry(key, value, value, context, leftquote, rightquote, leftspaces, rightspaces))

    return self

  def read_from_po(self, f):
    MODE_MSGID = 1
    MODE_MSGSTR = 2
    MODE_MSGCTXT = 3

    current_mode = 0
    current_msgid = ''
    current_context = ''
    current_value = ''
    entries_under_construction = set()

    for line in f:
      line = line.strip("\r\n")
      if line.startswith("#"):
        if line.startswith("#. :src:"):
          entry = TranslationEntry(line[9:])
          self.append(entry)
          entries_under_construction.add(entry)
      elif line.startswith("msgid"):
        current_msgid = unescape_po(line[7:-1])
        current_mode = MODE_MSGID
      elif line.startswith("msgctxt"):
        current_context = unescape_po(line[9:-1])
        current_mode = MODE_MSGCTXT
      elif line.startswith("msgstr"):
        current_value = unescape_po(line[8:-1])
        current_mode = MODE_MSGSTR
      elif line.startswith('"'):
        string = unescape_po(line[1:-1])
        if current_mode == MODE_MSGID:
          current_msgid += string
        elif current_mode == MODE_MSGCTXT:
          current_context += string
        elif current_mode == MODE_MSGSTR:
          current_value += string
      elif line == '':
        # Do not write the special translation (charset etc.) for msgid ""
        if current_msgid != '':
          for entry in entries_under_construction:
            entry.context = current_context
            entry.value = current_value
            entry.src_value = current_msgid
        entries_under_construction = set()
        current_mode = 0
        current_msgid = ''
        current_context = ''
        current_value = ''

    # Write last entry even if the file does not end with a blank line.
    if current_msgid != '':
      for entry in entries_under_construction:
        entry.context = current_context
        entry.value = current_value

    return self

  def get_translated_entry(self, master_entry):
    if len(master_entry.value) == 0:
      return get_empty_string_entry()

    key = master_entry.key.strip()
    if key not in self.entries:
      raise TranslationException("Key '%s' not found in PO file (original text: '%s')" %
          (key, master_entry.value))

    values = self.entries[key]
    if len(values) == 1:
      return iter(values).next()
    else:
      # Try to resolve ambiguity by looking at the source text
      matching_entries = dict([(e.value, e) for e in values if e.src_value == master_entry.value])
      if len(matching_entries) == 1:
        return matching_entries.values()[0]
      else:
        raise TranslationException("Ambiguous translation for key '%s', original text '%s': %s" %
            (key, master_entry.value, ", ".join(["translation '%s', original text '%s'" %
                (e.value, e.src_value) for e in matching_entries])))

def escape_po(string):
  return string.replace('"', r'\"')

def unescape_po(string):
  return string.replace(r'\"', '"')

def read_context_file(f, contexts):
  for line in f:
    if line.strip(" \r\n") == '' or line.startswith('#'):
      continue
    key, context = line.strip("\r\n").split(" ", 1)
    contexts[key] = context

def read_shortcut_group_file(f):
  cur_set = set()
  groups = []
  key_to_group = {}
  for line in f:
    line = line.strip(" \r\n")
    if len(line):
      cur_set.add(line)
      key_to_group[line] = cur_set
    elif len(cur_set):
      groups.append(cur_set)
      cur_set = set()
  return (groups, key_to_group)

def get_shortcut(string):
  """Returns the (lowercased) letter after the first occurrence of '&' that is not followed by a '&'"""
  start = string.find('&')
  while start != -1:
    if start < len(string) - 1 and string[start+1] != '&':
      return string[start+1].lower()
    start = string.find('&', start+1)
  return None

def get_shortcut_weight(string, pos, existing_shortcut = ''):
  # Favor start of a word and uppercase letters
  result = 0
  if pos == 0 or string[pos-1] in " -_+":
    result = 500 if string[pos].upper() == string[pos] else 600
  else:
    result = 700 if string[pos].upper() == string[pos] else 800
  if existing_shortcut not in "abcdefghijklmnopqrstuvwxyz" and string[pos].lower() == existing_shortcut:
    result -= 500
  if string[pos].lower() not in "abcdefghijklmnopqrstuvwxyz" + existing_shortcut:
    # Do not select special characters like '(', ',', ')' if not necessary
    result += 500
  # Favor positions at the start of the string
  return result + pos // 10

def get_min_shortcut_weight(string, char, existing_shortcut):
  occurrences = []
  start = string.find(char)
  while start != -1:
    occurrences.append(start)
    start = string.find(char, start+1)
  return 9999 if not len(occurrences) else min(get_shortcut_weight(string, pos, existing_shortcut) for pos in occurrences)

def add_shortcut(string, shortcut):
  """Inserts an '&' before an occurrence of 'shortcut' in the specified string and returns the result.
  shortcut must be a lower-case letter that occurs in the (lowercased) string"""

  # List of tuples (position, value) where a lower value means a more favorable position
  start = string.lower().find(shortcut)
  min_weight = 9999
  position = -1
  while start != -1:
    weight = get_shortcut_weight(string, start)
    # When weights are equal, take the earlier position
    if weight < min_weight:
      position = start
      min_weight = weight
    start = string.lower().find(shortcut, start+1)

  if position == -1:
    raise Exception('Shortcut %s not found in string %s' % (shortcut, string))
  return string[:position] + '&' + string[position:]

def generate_shortcuts(master_file, translation_file, shortcut_groups):
  (groups, key_to_group) = read_shortcut_group_file(shortcut_groups)
  result = {}

  # The shortcut generation problem is an instance of the Assignment Problem:
  # Assign n workers (translated texts) to m jobs (letters) so that the total cost
  # is minimized. The cost is 9999 when the letter does not occur in the text, else
  # it is an indicator of how favorable that letter is for the text (e.g. it occurs
  # at the start of a word, is an upper-case letter or is a special character
  # like a number that is also a shortcut in the original text).

  for group in groups:
    # Find out which entries of the master file have shortcuts at all
    entries_with_shortcuts = [] # tuple (translated entry, existing shortcut)
    matrix = []
    letterset = set()
    for key in group:
      if ('Caption' not in key and 'Text' not in key) or key not in master_file.entries:
        continue
      for master_entry  in master_file.entries[key]:
        shortcut = get_shortcut(master_entry.value)
        if shortcut is None:
          continue
        translated_entry = translation_file.get_translated_entry(master_entry)
        entries_with_shortcuts.append((translated_entry, shortcut))
        for char in translated_entry.value.lower():
          if char != ' ':
            letterset.add(char)

    if not len(entries_with_shortcuts):
      continue

    letterset = sorted(letterset)

    for (entry, existing_shortcut) in entries_with_shortcuts:
      value = entry.value.lower()
      matrix.append([get_min_shortcut_weight(value, c, existing_shortcut) for c in letterset])

    from . import munkres
    m = munkres.Munkres()
    indexes = m.compute(matrix)

    for (entry_idx, letter_idx) in indexes:
      (entry, existing_shortcut) = entries_with_shortcuts[entry_idx]

      if matrix[entry_idx][letter_idx] == 9999:
        raise Exception("No conflict-free shortcut could be found for %s (translation of key %s)" % (entry.value, entry.key))

      result[entry.key] = letterset[letter_idx]

  return result

def get_empty_string_entry():
  return TranslationEntry("", "", "", False, False, 0, 0)

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Translation helper for Zusi translation files.',
      epilog='You can optionally specify an encoding argument after a file name, e.g. deutsch.txt@ISO-8859-1. ' +
          'The encoding defaults to UTF-8.')
  parser.add_argument('mode', choices=['zusi2pot', 'zusi2po', 'po2zusi', 'checkzusi'],
      help="Mode to operate in. The following modes are supported: " +
      " ### zusi2pot: Creates a .pot (PO template) file from the file specified by --master."
      " ### zusi2po: Creates a .po file using keys and context information from the file specified by --master " +
        "and translations from the file specified by --translation. This should only be necessary when " +
        "converting an existing translation project to .po files."
      " ### po2zusi: Creates a Zusi translation file (.txt) from the PO file specified by --po-file using " +
        "keys and context information from the file specified by --master")
  parser.add_argument('--master', '-m', action='append', nargs='+', type=myargparse.CodecFileType('r'),
      help='Zusi master translation files (deutsch.txt, GleisplanEditor.txt, ...). '
      + 'These are the files from which translation keys and their order will be taken.'
      + 'For po2zusi, only one file may be specified.', required=True)
  parser.add_argument('--translation', '-t', type=myargparse.CodecFileType('r'),
      help='Existing Zusi translation file of the target language.')
  parser.add_argument('--po-file', '-p', type=myargparse.CodecFileType('r'),
      help='Existing PO translation file of the target language.')
  parser.add_argument('--context', '-c', action='append', nargs='*', type=myargparse.CodecFileType('r'),
      help='List of context entries (disambiguation of identical source texts).')
  parser.add_argument('--shortcut-groups', '-s', type=myargparse.CodecFileType('r'),
      help='List of shortcut groups (translation keys that should not get the same keyboard shortcut). '
      + 'Each key should be on its own line, and the groups should be separated by an empty line. '
      + 'The file must also end with an empty line. '
      + 'If this option is supplied, shortcuts are generated for translations whose source strings '
      + 'contain a keyboard shortcut')
  parser.add_argument('--out', '-o', type=myargparse.CodecFileType('w'), help='Output file')
  parser.add_argument('--strip-shortcuts', '-ss', action='store_const', const=True,
      help='zusi2pot/zusi2po: Strip keyboard shortcuts from the Zusi file. Only affects source texts whose key contains "Caption" or "Text"')

  args = parser.parse_args()

  if args.mode == 'zusi2po' and args.translation is None:
    parser.error('Missing existing translation file (--translation/-t)')
  if args.mode == 'po2zusi' and args.po_file is None:
    parser.error('Missing existing translation file (--po-file/-p)')
  if args.mode == 'po2zusi' and len(args.master) != 1:
    parser.error('Need exactly one master file for po2zusi mode')
  if args.mode != 'checkzusi' and args.out is None:
    parser.error('Missing output file name (--out/-o)')
  if args.strip_shortcuts and args.mode not in ['zusi2pot', 'zusi2po']:
    parser.error('--strip-shortcuts can only be used with zusi2pot/zusi2po mode')

  contexts = {}
  if args.context is not None:
    for context_file in args.context:
      read_context_file(context_file[0], contexts)

  master_file = TranslationFile()
  for m in args.master:
    master_file.read_from_zusi(m[0], contexts, strip_shortcuts = args.strip_shortcuts)

  if args.mode == 'checkzusi':
    duplicate_key_entries = defaultdict(list)

    single_source = []
    multiple_sources = []
    for entries in master_file.entries.values():
      if len(entries) > 1:
        values = set([entry.value for entry in entries])
        (single_source if len(values) == 1 else multiple_sources).append(entries)

    if len(single_source) == 0 and len(multiple_sources) == 0:
      print("File is OK.")
    else:
      print("The following keys occur multiple times in the file, but with the same source text:")
      for group in single_source:
        print("  " + iter(group).next().key + ": '" + iter(group).next().value + "'")
      print("The following keys occur multiple times in the file with different source text:")
      for group in multiple_sources:
        print("  " + iter(group).next().key + ": " + ", ".join(["'" + entry.value + "'" for entry in group]))

    sys.exit(0)

  if args.mode == 'zusi2po':
    translation_file = TranslationFile().read_from_zusi(args.translation, {})
  elif args.mode == 'po2zusi':
    po_file = TranslationFile().read_from_po(args.po_file)

  outfile = args.out
  master_entries_by_value = defaultdict(list)
  for entry in master_file:
    master_entries_by_value[(entry.value, entry.context)].append(entry)

  if args.mode in ['zusi2pot', 'zusi2po']:
    # Print the entry for the empty string first
    master_file.entries_in_order.insert(0, get_empty_string_entry())

    # Keep the ordering of the master file.
    for master_entry in master_file:
      key = (master_entry.value, master_entry.context)
      if key not in master_entries_by_value:
        # no try + except KeyError here, this is a defaultdict
        continue

      # Get all entries with the same key and context
      all_entries = master_entries_by_value[key]

      if not len(all_entries):
        raise Exception("len(all_entries) == 0: %s" % master_entry)

      del master_entries_by_value[key]

      for e in all_entries:
        outfile.write("#. :src: %s" % e.key + os.linesep)
      if len(master_entry.context):
        outfile.write("msgctxt \"%s\"" % escape_po(master_entry.context) + os.linesep)
      outfile.write('msgid "%s"' % escape_po(master_entry.value) + os.linesep)
      if args.mode == 'zusi2pot':
        outfile.write('msgstr ""' + os.linesep)
      else:
        possible_translation_entries = [translation_file[entry.key] for entry in all_entries if entry.key in translation_file]
        possible_translations = set([entry.value for entry in possible_translation_entries])
        if len(possible_translations) == 1:
          outfile.write('msgstr "%s"' % escape_po(next(iter(possible_translations))) + os.linesep)
        else:
          print("Error: %d translations found for text '%s', context '%s', with the following set of keys:"
              % (len(possible_translations), master_entry.value, master_entry.context))
          for entry in all_entries:
            print("  %s" % entry.key)
          if len(possible_translations) > 0:
            print("Possible translations:")
            for possible_translation in possible_translations:
              print("  '%s'" % possible_translation)
              for entry in possible_translation_entries:
                if entry.value == possible_translation:
                  print("    %s" % entry.key)
          sys.exit(3)

      if master_entry.key == '':
        outfile.write("\"Content-Type: text/plain; charset=UTF-8\\n\"" + os.linesep)

      outfile.write(os.linesep)

  elif args.mode == 'po2zusi':
    if args.shortcut_groups:
      shortcuts = generate_shortcuts(master_file, po_file, args.shortcut_groups)

    for master_entry in master_file:
      translated_entry = po_file.get_translated_entry(master_entry)
      value = translated_entry.value
      if args.shortcut_groups and (master_entry.key in shortcuts):
        value = add_shortcut(value, shortcuts[master_entry.key])
      try:
        outfile.write("%s = %s%s%s%s%s" % (master_entry.key, " " * master_entry.leftspaces, "'" if master_entry.leftquote else "",
          value, "'" if master_entry.rightquote else "", " " * master_entry.rightspaces) + os.linesep)
      except UnicodeEncodeError as e:
        raise TranslationException("%s = '%s' cannot be written in the specified output encoding. Error message: %s" % (master_entry.key, value, os.linesep + e.message))
