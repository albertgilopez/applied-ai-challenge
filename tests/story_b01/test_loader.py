"""STORY-B01 R1: the strict YAML loader (app/strict_yaml.py).

`yaml.safe_load` keeps the last of two equal keys, expands aliases without limit, applies merge keys and
turns `on`, `1.10` and dates into other types. A manifest needs none of that, and each one lets two
readers see two different manifests. Each guard below has a canary in scripts/canaries.py.
"""

import pytest

from app.strict_yaml import RefusedConstruct, Unreadable, read_yaml_file, strict_load

NORMAL = """
apiVersion: marketplace/v1
owner: {team: a, contact: b@example.com}
tools:
  - {name: x, requires_human_approval: false, n: 3}
summary: |
  two
  lines
nothing: null
quoted: 'on'
"""


def test_a_normal_manifest_loads_as_plain_data():
    data = strict_load(NORMAL)
    assert data["tools"][0] == {"name": "x", "requires_human_approval": False, "n": 3}
    assert data["quoted"] == "on"
    assert data["nothing"] is None


@pytest.mark.parametrize(
    "text",
    [
        "a: 1\na: 2\n",
        "t:\n- r: false\n  r: true\n",
        "a: &x 1\nb: *x\n",
        "base: &b {k: 1}\nsvc:\n  <<: *b\n",
        "svc:\n  <<: {k: 1}\n",
        "blob: !!binary aGVsbG8=\n",
        "x: !custom 1\n",
        "on: push\n",
        "1: x\n",
        "? [a, b]\n: x\n",
        "version: 1.10\n",
        "when: 2026-10-10\n",
    ],
    ids=[
        "duplicate-top",
        "duplicate-nested",
        "alias",
        "merge-via-alias",
        "merge-inline",
        "binary-tag",
        "custom-tag",
        "bool-key",
        "int-key",
        "complex-key",
        "implicit-float",
        "implicit-date",
    ],
)
def test_constructs_a_manifest_never_needs_are_refused(text):
    with pytest.raises(RefusedConstruct):
        strict_load(text)


def test_an_alias_bomb_is_refused_before_it_expands():
    bomb = "a: &a [x, x, x, x, x, x, x, x, x, x]\n" + "".join(
        f"{chr(98 + i)}: &{chr(98 + i)} [{', '.join(['*' + chr(97 + i)] * 10)}]\n" for i in range(7)
    )
    with pytest.raises(RefusedConstruct):
        strict_load(bomb)


def test_a_syntax_error_is_unreadable_not_refused(tmp_path):
    bad = tmp_path / "m.yaml"
    bad.write_text("id: [unclosed", encoding="utf-8")
    with pytest.raises(Unreadable):
        read_yaml_file(bad, limit=1024)


def test_size_and_encoding_are_checked_before_parsing(tmp_path):
    big, latin = tmp_path / "big.yaml", tmp_path / "latin.yaml"
    big.write_text("#" * 2048, encoding="utf-8")
    latin.write_bytes("summary: caf\xe9\n".encode("latin-1"))
    with pytest.raises(Unreadable):
        read_yaml_file(big, limit=1024)
    with pytest.raises(Unreadable):
        read_yaml_file(latin, limit=1024)
    with pytest.raises(Unreadable):
        read_yaml_file(tmp_path / "missing.yaml", limit=1024)


def test_the_digest_is_of_the_bytes_read(tmp_path):
    import hashlib

    p = tmp_path / "m.yaml"
    p.write_bytes(b"a: 1\n")
    data, digest = read_yaml_file(p, limit=1024)
    assert data == {"a": 1}
    assert digest == hashlib.sha256(b"a: 1\n").hexdigest()
