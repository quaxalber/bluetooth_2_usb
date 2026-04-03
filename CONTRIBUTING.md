<!-- omit in toc -->
# Contributing to Bluetooth 2 USB

Thank you for considering contributing to Bluetooth 2 USB! We value your effort and are happy to provide guidelines to help you get started. Following these guidelines helps to communicate that you respect the time of the developers managing and developing this open-source project. But don't be too concerned if you're still new to all this. The maintainers are happy to assist and guide new contributors!

<!-- omit in toc -->
## Table of Contents

- [1. Code of Conduct](#1-code-of-conduct)
- [2. Getting Started](#2-getting-started)
- [3. Coding Style](#3-coding-style)
  - [3.1. Best Practices for Clean and Maintainable Code](#31-best-practices-for-clean-and-maintainable-code)
    - [3.1.1. General Guidelines](#311-general-guidelines)
    - [3.1.2. Object-Oriented Programming (OOP) Guidelines](#312-object-oriented-programming-oop-guidelines)
  - [3.2. Code Formatting with Black](#32-code-formatting-with-black)
- [4. Pull Requests](#4-pull-requests)
- [5. Reporting Issues](#5-reporting-issues)

## 1. Code of Conduct

By participating in this project, you are expected to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## 2. Getting Started

- [Fork the repository](https://docs.github.com/en/get-started/quickstart/fork-a-repo) on GitHub
 
- Install required packages to your Linux machine:
 
  ```console
  sudo apt update && sudo apt install -y git python3.11 python3.11-venv python3.11-dev
  ```

- Clone the forked repository:
 
  ```console
  git clone https://github.com/YOUR-ACCOUNT/bluetooth_2_usb.git
  ```

- Initialize submodules:
 
  ```console
  cd bluetooth_2_usb && git submodule update --init --recursive
  ```

- Create a virtual Python environment:
 
  ```console
  python3.11 -m venv venv
  ```
 
- Install submodules in virtual Python environment:
 
  ```console
  venv/bin/pip3.11 install submodules/*
  ``` 

- Open the repo in your favorite IDE
 
- Make sure that your IDE is using python3.11 from `bluetooth_2_usb/venv/bin/`, e.g. in VS Code:
 
  `CTRL + SHIFT + P` > type `Python Select Interpreter` > select `Enter interpreter path`

## 3. Coding Style

We value code readability and consistency. To ensure that your contributions align with the project's coding style, please follow these guidelines:

### 3.1. Best Practices for Clean and Maintainable Code

Adherence to widely accepted best practices is crucial for creating code that is clean, maintainable, and efficient. Below are some of the general guidelines you should follow, particularly with regard to Object-Oriented Programming (OOP).

#### 3.1.1. General Guidelines

- Opt for readability over compact code: make sure your code is easy to read and understand.
- Use [meaningful](https://www.youtube.com/watch?v=-J3wNP6u5YU) variable and function names.
- Keep functions [small and focused](https://www.youtube.com/watch?v=CFRhGnuXG-4).
- Document your code [properly](https://www.youtube.com/watch?v=Bf7vDBBOBUA) with comments and docstrings.

#### 3.1.2. Object-Oriented Programming (OOP) Guidelines

- Use encapsulation by limiting the direct manipulation of object attributes and using methods instead.
- Employ inheritance [wisely](https://www.youtube.com/watch?v=hxGOiiR9ZKg) to reuse code and create a logical relationship between classes.
- Leverage [polymorphism](https://www.youtube.com/watch?v=rQlMtztiAoA) to allow objects to take on more than one form.
- Follow the Single Responsibility Principle: a class should have only one reason to change.
- Make use of [design patterns](https://www.youtube.com/watch?v=J1f5b4vcxCQ) where appropriate.

To learn more about OOP and best practices, consider reviewing:

- [All videos by CodeAesthetic](https://www.youtube.com/@CodeAesthetic)
- [Clean Code by Robert C. Martin](https://www.amazon.com/Clean-Code-Handbook-Software-Craftsmanship/dp/0132350882)
- [Python 3 Object-Oriented Programming by Dusty Phillips](https://www.amazon.com/Python-3-Object-Oriented-Programming/dp/1789615852)
- [The SOLID Principles in Python](https://realpython.com/tutorials/solid/)

### 3.2. Code Formatting with Black

We use [Black](https://black.readthedocs.io/en/stable/) for code formatting. Before committing any code, please make sure to run Black to keep the coding style consistent:

Install Black:

```bash
pip install black
```

Run Black:

```bash
black .
```

This will automatically reformat your code to conform to the project's coding style. There are also plugins available for many IDEs, e.g. [for vscode](https://code.visualstudio.com/docs/python/formatting).

## 4. Pull Requests

- Create a new branch for each feature or bugfix you are working on.
- Commit your changes following the [coding style](#3-coding-style) guidelines. Add concise commit messages.
- Push your changes to your fork.
- [Create a new Pull Request](https://docs.github.com/en/github/collaborating-with-issues-and-pull-requests/about-pull-requests) targeting the main branch of the official repository. A short description helps the maintainers reviewing the changes.

## 5. Reporting Issues

Please use the GitHub [issue tracker](https://github.com/quaxalber/bluetooth_2_usb/issues) to report any bugs or to request new features. Make sure to check for existing issues that are related to yours before creating a new one.

---

Thank you for taking the time to contribute!

