# JellyBeam — plano da build customizada com injeção do servidor

> O projeto passou a se chamar **JellyBeam** ao deixar de ser só Samsung.
> Referências a "JellyBeam" neste documento são do nome anterior.

Documento de projeto. Escrito em 11/09/2026, a partir de investigação feita no
servidor Contos (Jellyfin 12.0, 43 usuários).

---

## 1. O problema que isto resolve

Customizações do Jellyfin se dividem em duas categorias, e elas têm alcances
**muito** diferentes:

| Tipo | Como chega ao cliente | Alcança TV? |
|---|---|---|
| **CustomCss** (tema) | buscado da API em tempo de execução | **sim** |
| **JavaScript** injetado no `index.html` do servidor | só quem baixa o HTML do servidor | **não** |

O motivo: o app de Tizen (e o de WebOS) **empacota o `jellyfin-web` dentro do
próprio pacote**, em tempo de build. Ele nunca pede `index.html` ao servidor —
só conversa com a API.

Verificado em produção: em 8.331 requisições ao proxy reverso, **zero** vieram de
Tizen, WebOS ou Android TV. E a documentação oficial confirma o desenho:

```bash
JELLYFIN_WEB_DIR=../jellyfin-web/dist npm ci --no-audit
```

Consequência prática: plugins de injeção — o Media Bar Enhanced, o Custom
JavaScript plugin, ou scripts próprios — **não funcionam na TV**, por mais que
funcionem no navegador.

---

## 2. A ideia central: empacotar ponteiros, não código

A tentação é embutir o código customizado no `.wgt`. Isso funciona, mas prende
cada alteração a uma recompilação e reinstalação em cada aparelho.

**Melhor: embutir apenas as tags que apontam para o servidor.**

```html
<link rel="stylesheet" href="{BASE}/MediaBarEnhanced/Resources/mediaBarEnhanced.css">
<script src="{BASE}/MediaBarEnhanced/Resources/mediaBarEnhanced.js" defer></script>
<script src="{BASE}/web/cs-nav.js" defer></script>
```

> ### ⛔ A URL NÃO vai para o código
>
> `{BASE}` é substituído em tempo de build pelo valor que o usuário informou na
> interface. O endereço vive **apenas** na configuração local
> (`~/.config/jellybeam/`), nunca no repositório.
>
> Este repositório é público. Endereço de servidor de terceiro é dado privado —
> expõe a infraestrutura de quem usa, e não tem por que estar versionado.
> No código ficam o campo vazio, a validação e o `{BASE}` como marcador.

Com isso:

- instala **uma vez** por aparelho
- toda alteração posterior no script, no tema ou na configuração do plugin
  chega à TV **sem recompilar nada**
- o `.wgt` fica pequeno e estável, e não precisa acompanhar versão do servidor

O preço é que a URL fica fixa **no pacote gerado** — o que é correto, já que o
pacote é feito para um servidor específico. Quem instalar para outro servidor
gera outro pacote, informando outra URL na interface. Nada disso toca o código.

---

## 3. Onde injetar, no fluxo atual do código

Hoje, em `services/docker.py`, `build_jellyfin_app_async()`:

```bash
cd /workspace
git clone https://github.com/jellyfin/jellyfin-tizen.git   # se não existir
cd jellyfin-tizen
tizen build-web
tizen package -t wgt -s JellyBeam
```

O `www/` já existe nesse ponto (vem do preparo do ambiente). O `tizen build-web`
processa `www/` e gera `.buildResult/`; o `package` empacota esse resultado.

**Ponto de injeção: entre o `git clone` e o `tizen build-web`, editando
`jellyfin-tizen/www/index.html`.**

Injetar antes do `build-web` — e não no `.buildResult/` — porque o `build-web`
é quem decide o que entra no pacote. Editar depois dele é apostar que o
`package` não vai refazer nada.

A edição precisa ser **idempotente**: remover qualquer tag anterior antes de
inserir a nova, para o caso de rebuild sobre um `www/` já modificado.

---

## 4. Riscos a verificar na primeira build

**(a) Política de origem do widget.** O app roda de uma origem local; carregar
script de `https://…` é requisição de origem cruzada. Precisa que o `config.xml`
do widget permita (`<access origin="*" subdomains="true"/>`) e que não haja um
CSP no `index.html` bloqueando `script-src`.

*Se bloquear:* o plano B é embutir o código em vez do ponteiro. Perde-se a
atualização automática, mas o resto funciona.

**(b) Ordem de carregamento.** Os scripts usam `window.ApiClient`, que só existe
depois do bundle do Jellyfin. O `defer` garante execução após o parse do HTML,
mas não após a inicialização do app. O `cs-nav.js` já trata isso — ele espera o
`ApiClient` aparecer e reage via `MutationObserver`. Scripts novos precisam do
mesmo cuidado.

**(c) Servidor indisponível no boot.** Se a TV ligar antes do servidor responder,
as tags falham silenciosamente e o app abre sem customização. Aceitável: um
recarregamento resolve. Não vale adicionar retry no `index.html`.

---

## 5. WebOS — a premissa deste plano estava errada

> **Investigado em 12/09/2026. Conclusão: não há nada a fazer no app.**
> O que segue nesta seção descreve o toolchain, que continua correto, mas a
> motivação caiu por terra.

O plano assumia que WebOS teria o mesmo problema do Tizen. Não tem, e a
diferença é estrutural. Abrindo o `.ipk` publicado (`org.jellyfin.webos`,
v1.2.2, **272 KB descompactado**) encontra-se:

```html
<iframe id="contentFrame" style="display: none;">
```
```js
baseurl + "/web/"   →   src = url
```

O cliente de WebOS **não embute o jellyfin-web**. Ele é uma casca com um
iframe apontado para `<servidor>/web/`. A página que renderiza na TV é a do
próprio servidor, buscada a cada abertura.

Consequência: **as customizações do servidor já chegam à LG hoje**, sem
pacote customizado, sem injeção, sem reassinatura. O `cs-nav.js` injetado no
`index.html` do servidor vale para WebOS do mesmo jeito que vale para
navegador.

Compare com o Tizen, cujo `.wgt` traz o `jellyfin-web` inteiro dentro: lá a
TV nunca pede a página ao servidor, e por isso toda a maquinaria da seção 6
precisa existir.

### E por isso o app não implementa WebOS

O cliente Jellyfin está na Loja LG desde maio de 2024. Quem instala por lá
recebe as customizações igualmente, **sem** Modo Desenvolvedor, sem senha e
sem o temporizador de 50 horas. Um instalador por sideload seria pior que a
loja para praticamente todo mundo.

Sobram apenas casos de borda: TV cuja loja não oferece o app, WebOS antigo
demais, ou a necessidade de travar uma versão específica. Não é o bastante
para sustentar um caminho de instalação não testado.

O código de `services/webos.py` chegou a ser escrito e foi descartado. O SDK
existe dentro da imagem Docker (`/webOS_TV_SDK/CLI/bin`, ares-cli 1.11.0) e
os comandos abaixo foram conferidos — se um dia houver motivo, o caminho está
mapeado.

### O toolchain, para referência futura

O SDK é diferente e há **uma restrição séria**.

| | Tizen | WebOS |
|---|---|---|
| SDK | Tizen Studio (`tizen`, `sdb`) | LG SDK (`ares-cli`) |
| Pacote | `.wgt` | `.ipk` |
| Instalação | `sdb connect` + `tizen install` | `ares-setup-device`, `ares-novacom --getkey`, `ares-install` |
| Docker | imagem `install-jellyfin-tizen` | o `jellyfin-webos` traz um `dev.sh` com imagem própria |
| **Validade da instalação** | certificado de ~2 anos | **sessão de Dev Mode de 50 horas** |

### O problema das 50 horas

O Modo Desenvolvedor do WebOS tem um temporizador de **50 horas de tempo de
relógio** — não de tempo ligado. Quando expira, a TV faz logout e **remove os
apps sideloaded**. Isso é limitação da plataforma LG, não do Jellyfin.

Existe renovação automática: a TV não precisa estar ligada, e dá para chamar a
API de extensão por cron. O `webosbrew` mantém um `devmode-reset.sh`, e o webOS
Dev Manager expõe uma URL de renovação que pode ser chamada por agendador.

**Consequência para o projeto:** no WebOS, "instalar" não é evento único. Sem
renovação automática, o app some em dois dias. Qualquer suporte a WebOS no
JellyBeam precisa incluir a renovação — ou avisar o usuário de forma
inequívoca, senão vira suporte para "o app sumiu".

### Vale a pena?

Desde maio de 2024 o cliente Jellyfin está na loja da LG para todas as versões
de WebOS. Ou seja, **o sideload no WebOS só se justifica para build customizada**
— que é exatamente o nosso caso, mas é um caso de nicho.

Recomendação: **fazer o Tizen primeiro e completo**. WebOS numa segunda etapa, e
só se a renovação automática estiver resolvida.

---

## 6. Plano de implementação

### Fase 1 — injeção no Tizen (o essencial) — ✅ código pronto, falta testar na TV

1. ✅ Novo módulo `services/customization.py`:
   - `inject(www_dir, base_url, resources)` — edita `www/index.html` de forma
     idempotente
   - `remove(www_dir)`, `is_injected(www_dir)`
2. ✅ Chamado em `build_jellyfin_app_async()`, entre o clone e o `build-web`.
   O build foi dividido em dois `docker exec` para abrir esse espaço.
3. ✅ Configuração, **não** constante de código:
   - `utils/constants.py`: só a **lista de recursos** (caminhos relativos)
   - `utils/config.py`: `customization.server_url` e `customization.enabled`,
     em `~/.config/jellybeam/`, fora do controle de versão
4. ⬜ Build, instalar no projetor, e **verificar no Web Inspector** que os
   scripts carregaram

**Critério de pronto:** a barra de destaque e a navegação de topo aparecem no
projetor, e uma alteração no `cs-nav.js` do servidor chega lá sem recompilar.

#### Diferenças em relação ao que estava planejado aqui

- **Nomes em inglês.** O plano dizia `customizacao.py` / `injetar()`. Todo o
  resto do código é em inglês, e um módulo isolado em português destoaria num
  repositório público com 28 traduções.
- **O marcador `{BASE}` não foi necessário.** Os recursos são caminhos
  relativos e a base é concatenada em tempo de execução, o que dá o mesmo
  resultado sem um template para substituir. A garantia continua a mesma: no
  código só existem caminhos relativos.
- **Edição no host, não dentro do container.** O workspace é bind-mount
  (`/tmp/jellybeam` → `/workspace`), então o `index.html` que o container vai
  compilar é gravável direto daqui. Sem `docker exec`, sem escape de shell, e
  o módulo virou lógica pura de arquivo — testável sem Docker.
- **Desligado por padrão.** Quem não configurar URL nenhuma tem exatamente o
  build de antes; o `index.html` não é tocado.

### Fase 2 — interface — ✅ pronta

5. ✅ Campo **"Jellyfin Server URL"** na tela de preferências, no grupo
   *Server Customization* da aba Geral
6. ✅ Chave **"Apply Server Customizations"**. Em vez de ligar sozinha quando a
   URL aparece, ela fica **desabilitada enquanto não houver URL** — mostrar a
   dependência é melhor do que mudar o estado por conta própria enquanto o
   usuário digita. Apagar a URL desliga a chave, porque deixá-la ligada sem
   endereço quebraria só na hora do build.
7. ✅ Botão **"Test"** que consulta `/System/Info/Public` fora da thread
   principal. Confere também se a resposta *parece* Jellyfin — um servidor web
   qualquer devolve 200 em muitos caminhos, e sem essa checagem o usuário
   levaria sinal verde e uma build quebrada.

**Critério de pronto:** dá para instalar sem editar código. ✅

### Fase 3 — WebOS — ❌ cancelada, ver seção 5

Investigada e descartada em 12/09/2026, não por dificuldade mas por falta de
motivo: o cliente de WebOS carrega a interface do servidor por iframe, então
as customizações já chegam sem nada disso. Quem tem TV LG instala pela loja
e recebe o mesmo resultado, sem Modo Desenvolvedor nem as 50 horas.

O que se descobriu no caminho, e vale guardar:

- o SDK do LG já está dentro da imagem Docker que o app usa
  (`/webOS_TV_SDK/CLI/bin`, ares-cli 1.11.0), incluindo `ares-extend-dev`,
  que renova a sessão de Modo Desenvolvedor
- existe `.ipk` publicado em `jellyfin/jellyfin-webos/releases`
- o `.ipk` é um pacote Debian (`ar` + `data.tar.gz`), não um zip como o `.wgt`
- WebOS não exige assinatura de código, ao contrário do Tizen

As descrições do app foram revertidas para falar só de Samsung: anunciar LG
sem entregar instalação seria prometer o que não existe.

### Fase 4 — robustez

13. Detectar CSP/origem bloqueada e cair para o modo "código embutido"
14. Registrar no log qual modo foi usado
15. Teste de fumaça pós-instalação: abrir o app e conferir que os recursos
    carregaram

### Fase 5 — player nativo (build OSA)

O build OSA troca o `<video>` HTML5 pelo AVPlay da Samsung. Ganha codecs e
perde configuração: o `avplayVideoPlayer.js` do jellyfin-tizen usa o mínimo
da API. O build customizado aplica um patch nesse arquivo (ver
`customization.patch_avplay`); o que já está feito e o que falta:

- ✅ **Proporção** — `setDisplayMethod`. Sem ele a plataforma estica tudo para
  16:9. Padrão `LETTER_BOX`; `AUTO_ASPECT_RATIO` foi testado no LSP3 e esticou
  igual ao `FULL_SCREEN`, apesar da referência dizer que segue o DAR/PAR.
  Menu "Proporção" do jellyfin-web habilitado via `supports('SetAspectRatio')`.
- ✅ **4K** — `setStreamingProperty('SET_MODE_4K')` antes do `prepare`, **só
  se** `productinfo.isUdPanelSupported()`. Não é inofensivo em 1080p: no LSP3
  derrubou a reprodução inteira (tela escura).
- ✅ **Tela acesa** — `webapis.appcommon.setScreenSaver(SCREEN_SAVER_OFF)`
  enquanto reproduz, `ON` em pause/stop. `tizen.power` **não existe** na TV
  (sonda no LSP3: `undefined`); AppCommon é pública, desde Tizen 2.3, sem
  privilégio. O privilégio `power` que chegou a ser adicionado ao manifesto
  foi removido.
- ✅ **Legendas** — confirmado pelo inspetor remoto no LSP3: o `.vtt` externo
  baixa, o AVPlay lê e entrega cada cue em `onsubtitlechange` com duração, e
  o player só escrevia no console — **ninguém desenhava**. O patch desenha
  numa camada HTML, com tamanho/fonte/cor/sombra/posição lidos das
  preferências de legenda do jellyfin-web (`*subtitleappearance*` no
  `localStorage`), sanitizando o HTML das cues (só `<i> <b> <u> <br>`).
- 🔧 **Depuração na TV** — `sdb shell 0 debug <app-id>` abre o inspetor numa
  porta; `http://<tv>:<porta>/json` lista a página e o WebSocket do DevTools
  é acessível direto pela rede, sem `sdb forward`. A sessão cai a cada ~20 s
  (reconectar). `dlog` vem vazio em firmware de consumidor.
- ⏳ **Buffer** — `setBufferingParam` para reduzir a espera ao pular cena.
  Precisa de teste na rede real para não piorar.
- ❌ **Velocidade** — `setSpeed` só aceita múltiplos inteiros e altera o
  áudio fora de 1×. Não é o 1,25×/1,5× que se espera; não vale expor.
- ⏳ **Codecs** — o perfil declara h264/hevc/vp9 e áudio até eac3/flac. AV1,
  DTS e TrueHD dependem do modelo; declarar às cegas dá tela preta ou vídeo
  mudo. Só com detecção em tempo de execução (`webapis.productinfo`).

---

## 7. O que este plano **não** resolve

- **Android TV, Roku, Kodi**: são clientes nativos, sem página para injetar.
  Nenhuma customização — nem CSS — chega neles. No servidor Contos são ~24 dos
  43 usuários.
- **Atualização do app**: se a TV atualizar o app da loja por cima do
  sideloaded, a customização se perde. No Tizen isso não costuma acontecer com
  pacote sideloaded, mas no WebOS a remoção por expiração é certa.

---

## 8. Referências

- [jellyfin/jellyfin-tizen](https://github.com/jellyfin/jellyfin-tizen) — build e certificados
- [jellyfin/jellyfin-webos](https://github.com/jellyfin/jellyfin-webos) — `dev.sh`, `ares-*`
- [Guia de instalação permanente no WebOS](https://github.com/dab2020/Guides/blob/main/jellyfinwebos/index.md)
- [Manter o Dev Mode do WebOS vivo](https://elis.nu/blog/2022/07/keeping-webos-developer-mode-alive-with-home-assistant/)
- [CSS Customization — Jellyfin](https://jellyfin.org/docs/general/clients/css-customization/)
- [Issue #288 — CSS do servidor no Tizen](https://github.com/jellyfin/jellyfin-tizen/issues/288)
