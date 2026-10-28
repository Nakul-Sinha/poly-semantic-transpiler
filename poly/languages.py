"""The public language registry shared by the API, UI and CLI."""
from __future__ import annotations

LANGUAGES = {
    "py": {"name": "Python", "extension": ".py", "example": "def gcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a\n\nprint(gcd(48, 36))\n"},
    "js": {"name": "JavaScript", "extension": ".js", "example": "function gcd(a, b) {\n  while (b !== 0) { const t = b; b = a % b; a = t; }\n  return a;\n}\nconsole.log(gcd(48, 36));\n"},
    "c": {"name": "C", "extension": ".c", "example": "#include <stdio.h>\nint gcd(int a, int b) {\n    while (b) { int t = b; b = a % b; a = t; }\n    return a;\n}\nint main(void) { printf(\"%d\\n\", gcd(48, 36)); return 0; }\n"},
    "cpp": {"name": "C++", "extension": ".cpp", "example": "#include <iostream>\nint gcd(int a, int b) {\n    while (b) { int t = b; b = a % b; a = t; }\n    return a;\n}\nint main() { std::cout << gcd(48, 36) << '\\n'; }\n"},
    "java": {"name": "Java", "extension": ".java", "example": "public class Main {\n    static int gcd(int a, int b) {\n        while (b != 0) { int t = b; b = a % b; a = t; }\n        return a;\n    }\n    public static void main(String[] args) { System.out.println(gcd(48, 36)); }\n}\n"},
    "cs": {"name": "C#", "extension": ".cs", "example": "using System;\nclass Program {\n    static int Gcd(int a, int b) {\n        while (b != 0) { int t = b; b = a % b; a = t; }\n        return a;\n    }\n    static void Main() { Console.WriteLine(Gcd(48, 36)); }\n}\n"},
    "go": {"name": "Go", "extension": ".go", "example": "package main\nimport \"fmt\"\nfunc gcd(a, b int) int {\n    for b != 0 { a, b = b, a % b }\n    return a\n}\nfunc main() { fmt.Println(gcd(48, 36)) }\n"},
    "rust": {"name": "Rust", "extension": ".rs", "example": "fn gcd(mut a: i64, mut b: i64) -> i64 {\n    while b != 0 { let t = b; b = a % b; a = t; }\n    a\n}\nfn main() { println!(\"{}\", gcd(48, 36)); }\n"},
    "ruby": {"name": "Ruby", "extension": ".rb", "example": "def gcd(a, b)\n  while b != 0\n    a, b = b, a % b\n  end\n  a\nend\nputs gcd(48, 36)\n"},
    "php": {"name": "PHP", "extension": ".php", "example": "<?php\nfunction gcd($a, $b) {\n    while ($b != 0) { $t = $b; $b = $a % $b; $a = $t; }\n    return $a;\n}\necho gcd(48, 36), PHP_EOL;\n"},
}

ALIASES = {"python": "py", "python3": "py", "javascript": "js", "c++": "cpp",
           "c#": "cs", "csharp": "cs", "golang": "go", "rs": "rust", "rb": "ruby"}


def language(value: str) -> str:
    key = str(value).strip().lower()
    key = ALIASES.get(key, key)
    if key not in LANGUAGES:
        raise ValueError(f"Unsupported language {value!r}. Choose one of: " + ", ".join(LANGUAGES))
    return key
