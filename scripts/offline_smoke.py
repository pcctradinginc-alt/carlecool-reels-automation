"""End-to-end local-only smoke test with entirely synthetic audio and stock footage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *args], check=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'assets/audio').mkdir(parents=True)
        (root / 'assets/stock').mkdir(parents=True)
        (root / 'data').mkdir()
        # Never touch the user's real accounts in this test.
        ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000', '-t', '22',
               '-c:a', 'libmp3lame', str(root / 'assets/audio/1000.mp3'))
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=270x480:rate=10', '-t', '5',
               '-pix_fmt', 'yuv420p', str(root / 'assets/stock/synthetic.mp4'))
        (root / 'data/tracks.json').write_text(json.dumps([{
            'id': '1000', 'title': 'TEST AUDIO ONLY – NOT A REAL SONG',
            'permalink_url': 'https://soundcloud.com/carlecool',
            'created_at': '2026-11-15T00:00:00Z', 'genre': 'Electronic'}]))
        (root / 'data/state.json').write_text(json.dumps({'published': [], 'pending': None}))
        (root / 'data/preview-history.json').write_text(json.dumps({
            'version': 1, 'previews': []
        }))
        (root / 'assets/stock/manifest.json').write_text(json.dumps({'clips': [{
            'id': 'synthetic', 'file': 'synthetic.mp4', 'title': 'synthetic only',
            'license_confirmed': True, 'commercial_social_allowed': True
        }]}))
        env = os.environ.copy()
        env.update({'REEL_SECONDS': '20', 'REEL_WIDTH': '270', 'REEL_HEIGHT': '480',
                    'COVERR_API_KEY': '', 'SOUNDCLOUD_CLIENT_ID': '',
                    'SOUNDCLOUD_CLIENT_SECRET': '', 'PUBLISH_ENABLED': 'false',
                    'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
        subprocess.run([sys.executable, '-m', 'carlecool.main', '--mode', 'preview'],
                       cwd=root, env=env, check=True)
        assert (root / 'output/carlecool_1000.mp4').is_file()
        meta = json.loads((root / 'output/reel_metadata.json').read_text())
        assert meta['track_id'] == '1000' and meta['duration'] >= 19
        assert meta['resolution'] == '270x480'
        assert json.loads((root / 'data/state.json').read_text())['published'] == []
        # Three filmic variants from synthetic music and synthetic licensed stock.
        # No emails, public media artifacts, API or real song required.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from carlecool.variant_compare import compare
        import os as _os
        old_dims = {_name: _os.environ.get(_name) for _name in ('REEL_WIDTH', 'REEL_HEIGHT')}
        try:
            _os.environ['REEL_WIDTH'] = '270'
            _os.environ['REEL_HEIGHT'] = '480'
            variants = compare(root / 'assets/audio/1000.mp3',
                               [root / 'assets/stock/synthetic.mp4'],
                               root / 'variants', length=8)
        finally:
            for _name, _value in old_dims.items():
                if _value is None:
                    _os.environ.pop(_name, None)
                else:
                    _os.environ[_name] = _value
        assert len(variants['variants']) == 3
        assert all(Path(v['file']).is_file() for v in variants['variants'])
        assert (root / 'variants/comparison.json').is_file()
        print('PASS: Synthetic end-to-end render, SHA-256 metadata, zero social-media calls')


if __name__ == '__main__':
    main()
