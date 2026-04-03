<!-- omit in toc -->
# Contributing to Bluetooth 2 USB

Thank you for considering contributing to Bluetooth 2 USB! We value your effort and are happy to provide guidelines to help you get started. Following these guidelines helps to communicate that you respect the time of the developers managing and developing this open-source project.
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
- [6. Additional Resources](#6-additional-resources)

## 1. Code of Conduct

By participating in this project, you are expected to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## 2. Getting Started

- Fork the repository on GitHub
- Clone the forked repository to your machine
- Open the repo in your favorite IDE

## 3. Coding Style

We value code readability and consistency. To ensure that your contributions align with the project's coding style, please follow these guidelines:

### 3.1. Best Practices for Clean and Maintainable Code

Adherence to widely accepted best practices is crucial for creating code that is clean, maintainable, and efficient. Below are some of the general guidelines you should follow, particularly with regard to Object-Oriented Programming (OOP).

#### 3.1.1. General Guidelines

- Opt for readability over compact code: make sure your code is easy to read and understand.
- Use meaningful variable names and keep functions small and focused.
- Document your code properly with comments and docstrings.

#### 3.1.2. Object-Oriented Programming (OOP) Guidelines

- Use encapsulation by limiting the direct manipulation of object attributes and using methods instead.
- Employ inheritance wisely to reuse code and create a logical relationship between classes.
- Leverage polymorphism to allow objects to take on more than one form.
- Follow the Single Responsibility Principle: a class should have only one reason to change.
- Make use of design patterns where appropriate.

To learn more about OOP and best practices, consider reviewing:

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
- Commit your changes following the [coding style](#3-coding-style) guidelines.
- Push your changes to your fork.
- Create a new Pull Request targeting the main branch of the official repository.

## 5. Reporting Issues

Please use the GitHub [issue tracker](https://github.com/quaxalber/bluetooth_2_usb/issues) to report any bugs or to request new features. Make sure to check for existing issues that are related to yours before creating a new one.

## 6. Additional Resources

- [GitHub Pull Request documentation](https://docs.github.com/en/github/collaborating-with-issues-and-pull-requests/about-pull-requests)
- [GitHub Forking a repo documentation](https://docs.github.com/en/get-started/quickstart/fork-a-repo)

---

Thank you for taking the time to contribute!

