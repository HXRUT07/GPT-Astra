"""Package only built extension files and user installation instructions."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json

root = Path(__file__).resolve().parent.parent
build = root / 'dist'
manifest = json.loads((build / 'manifest.json').read_text(encoding='utf-8'))
required = ['manifest.json', 'content.js', manifest['background']['service_worker']]
for filename in required:
    if not (build / filename).is_file():
        raise SystemExit(f'Missing build file: {filename}; run npm run build first')

output = root / 'artifacts' / 'gpt-astra-token-hud.zip'
output.parent.mkdir(exist_ok=True)
with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for source in sorted(build.iterdir()):
        if source.is_file():
            archive.write(source, f'gpt-astra-token-hud/{source.name}')
    archive.write(root / 'README.md', 'gpt-astra-token-hud/README.md')
print(f'Created {output}')
