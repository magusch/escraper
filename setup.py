import setuptools


with open("requirements.txt") as fp:
    install_requires = fp.read().splitlines()

setuptools.setup(
    name="escraper",
    version="1.1.9.7",
    packages=setuptools.find_packages(),
    install_requires=install_requires,
    include_package_data=True,
)
