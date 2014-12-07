import argparse
import myargparse
import os
import sys
import re
from collections import defaultdict

class TranslationEntry:
  def __init__(self, key, value='', context='', leftquote='', rightquote='', leftspaces=0, rightspaces=0):
    self.key = key
    self.value = value
    self.context = context
    self.leftquote = leftquote
    self.rightquote = rightquote
    self.leftspaces = leftspaces
    self.rightspaces = rightspaces

  def __str__(self):
    return "'%s' [%s] = '%s'" % (self.key, self.context, self.value)

  def __repr__(self):
    return self.__str__()

def read_zusi_file(f, contexts, keep_order = False, strip_shortcuts = False):
  """Returns either a dict indexed by key (if keep_order == False) or a list of translation entries in the specified file."""
  result = []
  for line in f:
    try:
      (key, value) = line.strip("\r\n").split(" = ", 1)
    except ValueError:
      continue
    leftspaces = len(value) - len(value.lstrip(" "))
    rightspaces = len(value) - len(value.rstrip(" "))
    value = value.strip(" ")
    leftquote = len(value) > 0 and value[0] == "'"
    rightquote = len(value) > 1 and value[len(value) - 1] == "'"
    value = value.strip("'")
    if strip_shortcuts and ('Caption' in key or 'Text' in key):
      value = re.sub(r'(?<!&)&(?!&)', '', value) # negative lookbehind and lookahead
    try:
      context = contexts[key]
    except KeyError:
      context = ''
    result.append(TranslationEntry(key, value, context, leftquote, rightquote, leftspaces, rightspaces))
  f.close()
  if keep_order:
    return result
  else:
    return dict((item.key, item) for item in result)

def read_po_file(f):
  result = []

  MODE_MSGID = 1
  MODE_MSGSTR = 2
  MODE_MSGCTXT = 3

  current_mode = 0
  current_msgid = ''
  current_context = ''
  current_value = ''
  entries_under_construction = []

  for line in f:
    line = line.strip("\r\n")
    if line.startswith("#"):
      if line.startswith("#. :src:"):
        entries_under_construction.append(TranslationEntry(line[9:]))
    elif line.startswith("msgid"):
      current_msgid = line[7:-1].replace('\\"', '"')
      current_mode = MODE_MSGID
    elif line.startswith("msgctxt"):
      current_context = line[9:-1].replace('\\"', '"')
      current_mode = MODE_MSGCTXT
    elif line.startswith("msgstr"):
      current_value = line[8:-1].replace('\\"', '"')
      current_mode = MODE_MSGSTR
    elif line.startswith('"'):
      string = line[1:-1].replace('\\"', '"')
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
      result.extend(entries_under_construction)
      entries_under_construction = []
      current_mode = 0
      current_msgid = ''
      current_context = ''
      current_value = ''

  # Write last entry even if the file does not end with a blank line.
  if current_msgid != '':
    for entry in entries_under_construction:
      entry.context = current_context
      entry.value = current_value
  result.extend(entries_under_construction)

  return dict(((item.key, item.context), item) for item in result)

def read_context_file(f, contexts):
  for line in f:
    if line.strip(" \r\n") == '' or line.startswith('#'):
      continue
    key, context = line.strip("\r\n").split(" ", 1)
    contexts[key] = context

def write_zusi_file(f, translation_entries):
  for entry in translation_entries:
    f.write('%s = %d%s%s%d%s\n' % (entry.key, " " * entry.leftspaces, "'" if entry.leftquote else '', entry.value, "'" if entry.rightquote else '', " " * entry.rightspaces))
  f.close()

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

def get_translated_entry(master_entry, po_file):
  if len(master_entry.value):
    try:
      return po_file[(master_entry.key.strip(), master_entry.context)]
    except KeyError:
      raise Exception("Key '%s', context '%s' not found in PO file (original text: '%s')" %
          (master_entry.key.strip(), master_entry.context, master_entry.value))
  else:
    return get_empty_string_entry()

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

  master_entries_by_key = {}
  for entry in master_file:
    master_entries_by_key[entry.key] = entry

  # The shortcut generation problem is an instance of the Assignment Problem:
  # Assign n workers (translated texts) to m jobs (letters) so that the total cost
  # is minimized. The cost is 9999 when the letter does not occur in the text, else
  # it is an indicator of how favorable that letter is for the text (e.g. it occurs
  # at the start of a word, is an upper-case letter or is a special character
  # like a number that is also a shortcut in the original text).

  for group in groups:
    # Find out which entries of the master file have shortcuts at all
    entries_with_shortcuts = []
    matrix = []
    letterset = set()
    for key in group:
      if 'Caption' not in key and 'Text' not in key or key not in master_entries_by_key:
        continue
      master_entry = master_entries_by_key[key]
      shortcut = get_shortcut(master_entry.value)
      if shortcut is None:
        continue
      entries_with_shortcuts.append((key, shortcut))
      translated_entry = get_translated_entry(master_entry, translation_file)
      for char in translated_entry.value.lower():
        if char != ' ':
          letterset.add(char)

    if not len(entries_with_shortcuts):
      continue

    letterset = sorted(letterset)

    for entry in entries_with_shortcuts:
      master_entry = master_entries_by_key[entry[0]]
      existing_shortcut = get_shortcut(master_entry.value)
      translated_entry = get_translated_entry(master_entry, translation_file)
      value = translated_entry.value.lower()

      matrix.append([get_min_shortcut_weight(value, c, existing_shortcut) for c in letterset])

    from . import munkres
    m = munkres.Munkres()
    indexes = m.compute(matrix)

    for (entry_idx, letter_idx) in indexes:
      entry = entries_with_shortcuts[entry_idx]
      master_entry = master_entries_by_key[entry[0]]
      translated_entry = get_translated_entry(master_entry, translation_file)

      if matrix[entry_idx][letter_idx] == 9999:
        raise Exception("No conflict-free shortcut could be found for %s (translation of key %s)" % (translated_entry.value, translated_entry.key))

      result[entry[0]] = letterset[letter_idx]

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

  if args.mode == 'checkzusi':
    master_file = []
    for m in args.master:
      master_file += read_zusi_file(m[0], {}, keep_order = True)

    entries_by_key = {}
    keys_multiple_sources = []
    keys_multiple_occurrences = []
    for entry in master_file:
      try:
        entries_by_key[entry.key].append(entry)
      except KeyError:
        entries_by_key[entry.key] = [entry]

    for key, entries in entries_by_key.items():
      if len(entries) > 1:
        values = set([entry.value for entry in entries])
        if len(values) == 1:
          keys_multiple_occurrences.append(key)
        else:
          keys_multiple_sources.append(key)

    if len(keys_multiple_sources) == 0 and len(keys_multiple_occurrences) == 0:
      print("File is OK.")
    else:
      print("The following keys occur multiple times in the file, but with the same source text:")
      for key in keys_multiple_occurrences:
        print("  " + key + ": '" + entries_by_key[key][0].value + "'")
      print("The following keys occur multiple times in the file with different source text:")
      for key in keys_multiple_sources:
        print("  " + key + ": " + ", ".join(["'" + entry.value + "'" for entry in entries_by_key[key]]))

    sys.exit(0)

  contexts = {}
  if args.context is not None:
    for context_file in args.context:
      read_context_file(context_file[0], contexts)

  master_file = []
  for m in args.master:
    master_file += read_zusi_file(m[0], contexts, keep_order = True, strip_shortcuts = args.strip_shortcuts)

  if args.mode == 'zusi2po':
    translation_file = read_zusi_file(args.translation, {})
  elif args.mode == 'po2zusi':
    po_file = read_po_file(args.po_file)

  outfile = args.out
  master_entries_by_value = defaultdict(list)
  for entry in master_file:
    master_entries_by_value[(entry.value, entry.context)].append(entry)

  if args.mode in ['zusi2pot', 'zusi2po']:
    # Print the entry for the empty string first
    master_file.insert(0, get_empty_string_entry())

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
        outfile.write("msgctxt \"%s\"" % master_entry.context.replace('"', '\\"') + os.linesep)
      outfile.write('msgid "%s"' % master_entry.value.replace('"', '\\"') + os.linesep)
      if args.mode == 'zusi2pot':
        outfile.write('msgstr ""' + os.linesep)
      else:
        possible_translation_entries = [translation_file[entry.key] for entry in all_entries if entry.key in translation_file]
        possible_translations = set([entry.value for entry in possible_translation_entries])
        if len(possible_translations) == 1:
          outfile.write('msgstr "%s"' % next(iter(possible_translations)).replace('"', '\\"') + os.linesep)
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
      translated_entry = get_translated_entry(master_entry, po_file)
      value = translated_entry.value
      if args.shortcut_groups and (master_entry.key in shortcuts):
        value = add_shortcut(value, shortcuts[master_entry.key])
      outfile.write("%s = %s%s%s%s%s" % (master_entry.key, " " * master_entry.leftspaces, "'" if master_entry.leftquote else "",
          value, "'" if master_entry.rightquote else "", " " * master_entry.rightspaces) + os.linesep)
