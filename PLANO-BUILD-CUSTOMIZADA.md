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

## 5. WebOS — é possível, mas o custo é outro

Sim, dá para fazer o mesmo. O toolchain é diferente e há **uma restrição séria**.

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

### Fase 1 — injeção no Tizen (o essencial)

1. Novo módulo `services/customizacao.py`:
   - `injetar(www_dir, base_url, recursos)` — edita `www/index.html` de forma
     idempotente
   - `remover(www_dir)` — desfaz
2. Chamar `injetar()` em `build_jellyfin_app_async()`, entre o clone e o
   `build-web`
3. Configuração, **não** constante de código:
   - `utils/constants.py`: só a **lista de recursos** (caminhos relativos) e o
     marcador `{BASE}`
   - `utils/config.py`: a **URL do servidor**, lida e gravada em
     `~/.config/jellybeam/`, fora do controle de versão
4. Build, instalar no projetor, e **verificar no console remoto** que os scripts
   carregaram (`ares`/`sdb` dão acesso ao console; no Tizen, o `tizen`
   Web Inspector)

**Critério de pronto:** a barra de destaque e a navegação de topo aparecem no
projetor, e uma alteração no `cs-nav.js` do servidor chega lá sem recompilar.

### Fase 2 — interface

5. Campo **"URL do servidor Jellyfin"** na tela de preferências
6. Caixa **"Aplicar customizações do servidor"**, ligada por padrão quando a URL
   estiver preenchida
7. Validação: URL alcançável e respondendo `/System/Info/Public`

**Critério de pronto:** dá para instalar sem editar código.

### Fase 3 — WebOS (condicional)

8. Investigar se a imagem Docker do `jellyfin-webos` cabe no mesmo padrão de
   `services/docker.py`
9. Seletor **Tizen / WebOS** na tela de dispositivo
10. `services/webos.py` com o fluxo `ares-*`
11. **Renovação automática do Dev Mode** — sem isso, não lançar
12. Aviso explícito na interface sobre as 50 horas

**Critério de pronto:** instalar no LG e o app continuar lá depois de uma semana.

### Fase 4 — robustez

13. Detectar CSP/origem bloqueada e cair para o modo "código embutido"
14. Registrar no log qual modo foi usado
15. Teste de fumaça pós-instalação: abrir o app e conferir que os recursos
    carregaram

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
