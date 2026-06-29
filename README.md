

## Install Dependencies
```shell
# install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```shell
git clone https://github.com/JiuTian-VL/Optimus-1.git
cd Optimus-1
uv sync
source .venv/bin/activate

uv pip install -r requirements.txt

# install java,  clang, xvfb
sudo apt install clang
sudo apt-get install openjdk-8-jdk
sudo apt-get install xvfb

# install mineclip dependicies
uv pip install setuptools==65.5.1 wheel==0.38.0 x_transformers==0.27.1 dm-tree

# install minerl
cd minerl
uv pip install -r requirements.txt
uv pip install -e . # maybe slow
cd ..

# download our MCP-Reborn and compile
# url: https://drive.google.com/file/d/1GLy9IpFq5CQOubH7q60UhYCvD6nwU_YG/view?usp=drive_link
mv MCP-Reborn.tar.gz minerl/minerl
cd minerl/minerl
rm -rf MCP-Reborn
tar -xzvf MCP-Reborn.tar.gz
cd MCP-Reborn
./gradlew clean build shadowJar

# download steve1 checkpoint
# url: https://drive.google.com/file/d/1Mmwqv2juxMuP1xOZYWucnbKopMk0c0DV/view?usp=drive_link
unzip optimus1_steve1_ckpt.zip

# (optional) download full memory we provided on Hugging Face.
# url: https://huggingface.co/datasets/MinecraftOptimus/Optimus1_Memory/
Unzip it to src/optimus1/memories/v1
```

## How to run
> ! Before running the code, open src/optimus1/models/gpt4_planning.py, change the OpenAI api key to your own key.

1. start the server, Optimus1 connect the MineRL via the server
```shell
bash scripts/server.sh
```
2. test minerl environment
```shell
bash scripts/test_minerl.sh
```
3. test diamond benchmark
```shell
bash scripts/diamond.sh
```


