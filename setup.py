import setuptools


with open("requirements.txt") as fp:
    install_requires = fp.read().splitlines()

setuptools.setup(
    name="escraper",
    version="1.5.2",
    packages=setuptools.find_packages(),
    install_requires=install_requires,
    include_package_data=True,
    python_requires=">=3.11",
)
