import argparse
import os
import sys
import re
from collections import defaultdict

import logging
logging.basicConfig(level=logging.INFO)

linesep = '\r\n' # make it Windows compatible

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
      return next(iter(values))
    else:
      # Try to resolve ambiguity by looking at the source text
      matching_entries = dict([(e.value, e) for e in values if e.src_value == master_entry.value])
      if len(matching_entries) == 1:
        return next(iter(matching_entries.values()))
      else:
        raise TranslationException("Ambiguous translation for key '%s', original text '%s': %s" %
            (key, master_entry.value, ", ".join(["translation '%s', original text '%s'" %
                (e.value, e.src_value) for e in matching_entries])))

class ShortcutGroupFile:
  def __init__(self):
    self.groups = [] # list of sets of keys that form one shortcut group
    self.key_to_group = {}

  def read_from_file(self, f):
    cur_set = set()
    for line in f:
      line = line.strip(" \r\n")
      if len(line):
        cur_set.add(line)
        self.key_to_group[line] = cur_set
      elif len(cur_set):
        self.groups.append(cur_set)
        cur_set = set()

  def get_shortcut(self, string):
    """Returns the (lowercased) letter after the first occurrence of '&' that is not followed by a '&'"""
    start = string.find('&')
    while start != -1:
      if start < len(string) - 1 and string[start+1] != '&':
        return string[start+1].lower()
      start = string.find('&', start+1)
    return None

  def get_shortcut_weight(self, string, pos, source_shortcut='', existing_shortcut=''):
    # Favor start of a word and uppercase letters
    result = 0
    if pos == 0 or string[pos-1] in " -_+":
      result = 500 if string[pos].upper() == string[pos] else 600
    else:
      result = 700 if string[pos].upper() == string[pos] else 800
    if source_shortcut not in "abcdefghijklmnopqrstuvwxyz" and string[pos].lower() == source_shortcut:
      # Favor "special" source shortcuts
      result -= 500
    if string[pos].lower() not in "abcdefghijklmnopqrstuvwxyz" + source_shortcut:
      # Do not select special characters like '(', ',', ')' if not necessary
      result += 500
    # Do not change existing translated shortcuts if possible
    if string[pos].lower()  == existing_shortcut:
      result = 0
    # Favor positions at the start of the string
    return result + (pos // 10)

  def get_min_shortcut_weight(self, string, char, source_shortcut, existing_shortcut):
    occurrences = []
    start = string.find(char)
    while start != -1:
      occurrences.append(start)
      start = string.find(char, start+1)
    return 9999 if not len(occurrences) else min(self.get_shortcut_weight(string, pos, source_shortcut, existing_shortcut) for pos in occurrences)

  def add_shortcut(self, string, shortcut):
    """Inserts an '&' before an occurrence of 'shortcut' in the specified string and returns the result.
    shortcut must be a lower-case letter that occurs in the (lowercased) string"""

    # List of tuples (position, value) where a lower value means a more favorable position
    start = string.lower().find(shortcut)
    min_weight = 9999
    position = -1
    while start != -1:
      weight = self.get_shortcut_weight(string, start)
      # When weights are equal, take the earlier position
      if weight < min_weight:
        position = start
        min_weight = weight
      start = string.lower().find(shortcut, start+1)

    if position == -1:
      raise Exception('Shortcut %s not found in string %s' % (shortcut, string))
    return string[:position] + '&' + string[position:]

  def generate_shortcuts(self, master_file, translation_file, existing_translation):
    result = {}

    if len(existing_translation.entries):
      logging.info("Reusing shortcuts from existing translation as much as possible")

    # The shortcut generation problem is an instance of the Assignment Problem:
    # Assign n workers (translated texts) to m jobs (letters) so that the total cost
    # is minimized. The cost is 9999 when the letter does not occur in the text, else
    # it is an indicator of how favorable that letter is for the text (e.g. it occurs
    # at the start of a word, is an upper-case letter or is a special character
    # like a number that is also a shortcut in the original text).

    for group in self.groups:
      # Find out which entries of the master file have shortcuts at all
      entries_with_shortcuts = [] # tuple (translated entry, source shortcut, existing shortcut)
      matrix = []
      letterset = set()
      for key in group:
        if ('Caption' not in key and 'Text' not in key) or key not in master_file.entries:
          # Ampersands are only used for shortcuts in UI element captions. In other, application-internal texts,
          # it occurs unescaped.
          continue
        for master_entry  in master_file.entries[key]:
          source_shortcut = self.get_shortcut(master_entry.value)
          if source_shortcut is None:
            continue
          translated_entry = translation_file.get_translated_entry(master_entry)
          existing_shortcut = None
          try:
            existing_shortcut = self.get_shortcut(existing_translation.get_translated_entry(master_entry).value)
          except TranslationException:
            pass
          entries_with_shortcuts.append((translated_entry, source_shortcut, existing_shortcut))
          for char in translated_entry.value.lower():
            if char != ' ':
              letterset.add(char)

      if not len(entries_with_shortcuts):
        continue

      letterset = sorted(letterset)

      for (entry, source_shortcut, existing_shortcut) in entries_with_shortcuts:
        value = entry.value.lower()
        matrix.append([self.get_min_shortcut_weight(value, c, source_shortcut, existing_shortcut) for c in letterset])

      from . import munkres
      m = munkres.Munkres()
      indexes = m.compute(matrix)

      for (entry_idx, letter_idx) in indexes:
        (entry, source_shortcut, existing_shortcut) = entries_with_shortcuts[entry_idx]

        if matrix[entry_idx][letter_idx] == 9999:
          raise TranslationException("No conflict-free shortcut could be found for %s (translation of key %s)" % (entry.value, entry.key))

        result[entry.key] = letterset[letter_idx]

    return result

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

def get_empty_string_entry():
  return TranslationEntry("", "", "", False, False, 0, 0)

class TranslationHelper(object):
  def main(self, args):
    contexts = {}
    if args.context is not None:
      for context_file in args.context:
        logging.info("Reading context file {}".format(context_file[0].name))
        read_context_file(context_file[0], contexts)

    master_file = TranslationFile()
    for m in args.master:
      logging.info("Reading master translation file {}".format(m[0].name))
      master_file.read_from_zusi(m[0], contexts, strip_shortcuts = args.strip_shortcuts)

    shortcuts = ShortcutGroupFile()
    if args.shortcut_groups:
      logging.info("Reading shortcut group file {}".format(args.shortcut_groups.name))
      shortcuts.read_from_file(args.shortcut_groups)

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

    existing_translation = TranslationFile()
    if (args.translation):
      logging.info("Reading existing translation file {}".format(args.translation.name))
      existing_translation.read_from_zusi(args.translation, {})
    if args.mode == 'po2zusi':
      logging.info("Reading PO file {}".format(args.po_file.name))
      po_file = TranslationFile().read_from_po(args.po_file)

    outfile = args.out.open()
    logging.info("Writing to output file {}".format(outfile.name))
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
          outfile.write("#. :src: %s" % e.key + linesep)
        if len(master_entry.context):
          outfile.write("msgctxt \"%s\"" % escape_po(master_entry.context) + linesep)
        outfile.write('msgid "%s"' % escape_po(master_entry.value) + linesep)
        if args.mode == 'zusi2pot':
          outfile.write('msgstr ""' + linesep)
        else:
          possible_translation_entries = [existing_translation[entry.key] for entry in all_entries if entry.key in existing_translation]
          possible_translations = set([entry.value for entry in possible_translation_entries])
          if len(possible_translations) == 1:
            outfile.write('msgstr "%s"' % escape_po(next(iter(possible_translations))) + linesep)
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
          outfile.write("\"Content-Type: text/plain; charset=UTF-8\\n\"" + linesep)

        outfile.write(linesep)

    elif args.mode == 'po2zusi':
      shortcuts_by_key = shortcuts.generate_shortcuts(master_file, po_file, existing_translation)

      for master_entry in master_file:
        translated_entry = po_file.get_translated_entry(master_entry)
        value = translated_entry.value
        try:
          value = shortcuts.add_shortcut(value, shortcuts_by_key[master_entry.key])
        except KeyError:
          pass
        try:
          outfile.write("%s = %s%s" % (master_entry.key, " " * master_entry.leftspaces if "Streckenvorschau" in master_entry.key else "", value) + linesep)
        except UnicodeEncodeError as e:
          raise TranslationException("%s = '%s' cannot be written in the specified output encoding. Error message: %s" % (master_entry.key, value, linesep + e.message))
