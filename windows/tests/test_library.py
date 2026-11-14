import pytest

from pyrunner_host.library import ScriptLibrary, normalize_name


def test_normalize_name():
    assert normalize_name("hello") == "hello.py"
    assert normalize_name("My script.py") == "My script.py"
    with pytest.raises(ValueError):
        normalize_name("../x.py")
    with pytest.raises(ValueError):
        normalize_name("a/b.py")
    with pytest.raises(ValueError):
        normalize_name("")


def test_library_crud(tmp_path):
    library = ScriptLibrary(tmp_path)
    created = library.save(None, "one", "print(1)\n")
    assert created["name"] == "one.py"
    again = library.save(created["id"], "one.py", "print(2)\n")
    assert again["id"] == created["id"]
    assert library.get(created["id"])["source"] == "print(2)\n"
    renamed = library.rename(created["id"], "two")
    assert renamed["name"] == "two.py"
    other = library.save(None, "three", "x")
    with pytest.raises(ValueError):
        library.rename(other["id"], "two.py")
    library.delete(created["id"])
    assert [item["id"] for item in library.list_scripts()] == [other["id"]]
    with pytest.raises(KeyError):
        library.get(created["id"])


def test_seed_once(tmp_path):
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    library = ScriptLibrary(tmp_path / "lib")
    library.seed_if_empty([examples / "hello.py"])
    library.seed_if_empty([examples / "hello.py"])
    assert len(library.list_scripts()) == 1
