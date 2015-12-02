#!/usr/bin/env python3

import argparse
from trans_helper import translation_helper
from trans_helper import myargparse

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
  parser.add_argument('--out', '-o', type=myargparse.CodecFileType('w', deferred=True), help='Output file')
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

  translation_helper.TranslationHelper().main(args)
