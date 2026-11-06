# CAPRI para Linux

Este pacote contém os arquivos necessários para gerar uma versão AppImage da
CAPRI em uma distribuição Linux. O AppImage deve ser compilado no próprio Linux
e para a arquitetura do computador de destino; o executável Windows não é
compatível.

## Requisitos

- Python 3 com suporte a `venv` e `pip`
- AppImageTool disponível como `appimagetool`
- Ollama instalado e o modelo `llama3.2` baixado

## Gerar o AppImage

Na pasta da CAPRI, execute:

```sh
chmod +x linux/build_appimage.sh
./linux/build_appimage.sh
```

O arquivo será criado em `dist-linux/CAPRI-<arquitetura>.AppImage`. Para usar,
permita a execução e abra-o:

```sh
chmod +x dist-linux/CAPRI-*.AppImage
./dist-linux/CAPRI-*.AppImage
```

O Ollama e o modelo não são incluídos no AppImage; a CAPRI os utiliza
localmente, como na versão Windows. O histórico fica na pasta de dados local
do usuário Linux, em `~/.local/share/Capri` ou no diretório definido por
`XDG_DATA_HOME`.

## Limitação deste pacote

O AppImage não foi compilado nem testado neste computador porque não há Linux
ou WSL instalado. O script acima deve ser executado em um ambiente Linux para
gerar e validar o artefato final.
