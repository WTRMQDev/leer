import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="leer",
    version="0.0.1",
    author="Evil Morty, Crez Khansick, Sark Czenchi",
    author_email="TetsuwanAtomu@tuta.io", 
    description="Leer cryptocurrency (alpha testing)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/WTRMQDev/leer", 
    packages=setuptools.find_packages(exclude=["example", ".git"]),
    package_data = {'leer.rpc':['web_wallet/*']},
    include_package_data = True,
    install_requires=['setuptools', 'wheel', 'lnoise', 'secp256k1_zkp', 'lmdb', 'aiohttp', 'jsonrpcserver==3.5.6'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
