import argparse
import myargparse
import os
import sys

class TranslationEntry:
  def __init__(self, key, value, context, leftquote, rightquote, leftspaces, rightspaces):
    self.key = key
    self.value = value
    self.context = context
    self.leftquote = leftquote
    self.rightquote = rightquote
    self.leftspaces = leftspaces
    self.rightspaces = rightspaces

def read_zusi_file(f, contexts, keep_order = False):
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
        key, extras = line[9:].split('          ')
        extras = extras.split(',')
        entries_under_construction.append(TranslationEntry(key, "", "", int(extras[0]), int(extras[1]), int(extras[2]), int(extras[3])))
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

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Translation helper for Zusi translation files.')
  parser.add_argument('mode', choices=['zusi2pot', 'zusi2po', 'po2zusi'])
      help="Mode to operate in. The following modes are supported: " +
      " ### zusi2pot: Creates a .pot (PO template) file from the file specified by --master."
      " ### zusi2po: Creates a .po file using keys and context information from the file specified by --master " +
        "and translations from the file specified by --translation. This should only be necessary when " +
        "converting an existing translation project to .po files."
      " ### po2zusi: Creates a Zusi translation file (.txt) from the PO file specified by --po-file using " +
        "keys and context information from the file specified by --master")
  parser.add_argument('--master', '-m', type=myargparse.CodecFileType('r', 'ISO-8859-1'),
      help='Zusi master translation file (deutsch.txt). '
      + 'This is the file from which translation keys and their order will be taken.', required=True)
  parser.add_argument('--translation', '-t', type=myargparse.CodecFileType('r'),
      help='Existing Zusi translation file of the target language.')
  parser.add_argument('--po-file', '-p', type=myargparse.CodecFileType('r'),
      help='Existing PO translation file of the target language.')
  parser.add_argument('--context', '-c', action='append', nargs='*', type=myargparse.CodecFileType('r'),
      help='List of context entries (disambiguation of identical source texts).')
  parser.add_argument('--out', '-o', type=myargparse.CodecFileType('w'), help='Output file', required=True)

  args = parser.parse_args()

  if args.mode == 'zusi2po' and args.translation is None:
    parser.error('Missing existing translation file (--translation/-t)')
  if args.mode == 'po2zusi' and args.po_file is None:
    parser.error('Missing existing translation file (--po-file/-p)')

  contexts = {}
  if args.context is not None:
    for context_file in args.context:
      read_context_file(context_file[0], contexts)

  master_file = read_zusi_file(args.master, contexts, True)

  if args.mode == 'zusi2po':
    translation_file = read_zusi_file(args.translation, {})
  elif args.mode == 'po2zusi':
    po_file = read_po_file(args.po_file)

  outfile = args.out

  master_entries_by_value = {}
  for entry in master_file:
    try:
      master_entries_by_value[(entry.value, entry.context)].append(entry)
    except:
      master_entries_by_value[(entry.value, entry.context)] = [entry]

  if args.mode in ['zusi2pot', 'zusi2po']:
    # Print the entry for the empty string first
    master_file.insert(0, TranslationEntry("", "", "", False, False, 0, 0))

    # Keep the ordering of the master file.
    for master_entry in master_file:
      try:
        all_entries = master_entries_by_value[(master_entry.value, master_entry.context)]
      except KeyError:
        continue

      del master_entries_by_value[(master_entry.value, master_entry.context)]

      for e in all_entries:
        outfile.write("#. :src: %s          %d,%d,%d,%d%s" % (e.key, e.leftquote, e.rightquote, e.leftspaces, e.rightspaces, os.linesep))
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
    for master_entry in master_file:
      translated_entry = po_file[(master_entry.key, master_entry.context)]
      outfile.write("%s = %s%s%s%s%s" % (master_entry.key, " " * translated_entry.leftspaces, "'" if translated_entry.leftquote else "",
          translated_entry.value, "'" if translated_entry.rightquote else "", " " * translated_entry.rightspaces) + os.linesep)
