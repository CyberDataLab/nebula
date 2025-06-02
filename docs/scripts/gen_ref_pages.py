"""Generate the code reference pages and navigation."""

from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()

root = Path(__file__).parent.parent.parent
src = root / "nebula"

print(f"Generating API pages from {src}")

excluded_dirs = ["tests", "utils", "config"]

for path in sorted(src.rglob("*.py")):
    if any(excluded in path.parts for excluded in excluded_dirs):
        print(f"Skipping excluded directory: {path}")
        continue
    print(f"Generating API page for {path}")
    module_path = path.relative_to(src).with_suffix("")
    print(f"Module path: {module_path}")
    doc_path = path.relative_to(src).with_suffix(".md")
    print(f"Doc path: {doc_path}")
    full_doc_path = Path("api", doc_path)
    print(f"Full doc path: {full_doc_path}")

    parts = tuple(module_path.parts)
    if not parts:
        continue

    # Prepend 'nebula' to the parts to include the root module
    parts = ("nebula",) + parts

    if parts[-1] == "__init__":
        parts = parts[:-1]
        print(f"Parts: {parts}")
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")
    elif parts[-1] == "__main__":
        continue

    nav[parts] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        ident = ".".join(parts)

        custom_title = f"Documentation for {parts[-1].capitalize()} Module"
        fd.write("---\n")
        fd.write("hide:\n  - toc\n")
        fd.write("---\n")
        fd.write(f"# {custom_title}\n\n")
        if parts[-1].capitalize() == "Nebula":
            fd.write(
                "This API Reference is designed to help developers understand every part of the code, providing detailed information about functions, parameters, data structures, and interactions within the platform.\n\n On the left, you'll find the directory tree of the platform, including folders, functions, code, and documentation.\n\n"
            )
        fd.write(f"::: {ident}")

    mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))

with mkdocs_gen_files.open("api/SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
