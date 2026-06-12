# Non-Interactive Shell Commands

Use non-interactive flags with file operations so aliases or prompts do not hang
agent sessions:

```bash
cp -f source dest
mv -f source dest
rm -f file
rm -rf directory
cp -rf source dest
```

Use `ssh -o BatchMode=yes` and `scp -o BatchMode=yes` when applicable. Use
`HOMEBREW_NO_AUTO_UPDATE=1` for Homebrew commands that should not prompt or
spend time updating.
