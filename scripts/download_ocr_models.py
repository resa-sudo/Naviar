"""Explicit setup download of official weights; never reads document images."""
from pathlib import Path
import tarfile
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1] / ".document-lab" / "models"
MODELS = ("PP-OCRv5_mobile_det", "en_PP-OCRv5_mobile_rec")
BASE = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name in MODELS:
        destination = ROOT / name
        if (destination / "inference.yml").is_file():
            print(name + ": already available")
            continue
        archive = ROOT / (name + ".tar")
        urlretrieve(BASE + name + "_infer.tar", archive)
        destination.mkdir(exist_ok=True)
        # Copy regular files only; never extract paths, symlinks or devices.
        with tarfile.open(archive) as package:
            for member in package.getmembers():
                if not member.isfile():
                    continue
                filename = Path(member.name).name
                if filename not in {"inference.json", "inference.pdmodel", "inference.pdiparams", "inference.yml"}:
                    continue
                with package.extractfile(member) as source:
                    (destination / filename).write_bytes(source.read())
        archive.unlink()
        if not (destination / "inference.yml").is_file():
            raise RuntimeError("Official model package layout was not recognized")
        print(name + ": downloaded")


if __name__ == "__main__":
    main()
