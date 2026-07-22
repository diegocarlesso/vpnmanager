# VPN Manager — notas para trabalhar neste código

Veja `README.md` para instalação/execução/estrutura de pastas. Este arquivo cobre o que não é óbvio a partir do código.

## Agentes e skills do projeto

Este repo tem subagentes e skills dedicados em `../.claude/` (agents/skills, um nível acima, na raiz onde o Claude Code é invocado):

- **pyside6-desktop** — threading Qt (QThread/QThreadPool), sinais entre threads, diálogos modais, ciclo de vida de widgets.
- **windows-vpn-network** — `rasdial.exe`, `.pbk`, módulo PowerShell `VpnClient`, semântica real do RAS.
- **powershell-scripts** — contrato JSON dos scripts em `scripts/*.ps1`, elevação UAC, encoding.
- **skill diagnose-vpn-logs** — como ler `logs/` e `dist/logs/` para reconstruir a timeline de um bug antes de tocar em código.
- **skill build-release** — empacotar via PyInstaller (`VPNManager.spec`) e checklist de versão.

Use-os proativamente: a maioria dos bugs deste app é de concorrência entre threads ou de estado do Windows RAS que não bate com o que o app acha que sabe — não são bugs óbvios de ler uma função isolada.

## Modelo de threads (resumo — detalhes no agente `pyside6-desktop`)

- Main thread: `MainWindow` (UI).
- `VpnMonitor`: 1 `QThread` dedicada, faz polling (`rasdial` + `.pbk`) e emite `vpns_updated`. É a **única** fonte de verdade sobre status de conexão exibido na UI.
- `ConnectionService` / `VpnConfigService`: `QThreadPool`s separados para operações pontuais (connect/disconnect/reconnect vs. add/update/delete/detalhes).
- Estado "em andamento" vive em `Set[str]` na `MainWindow` (`_connect_ops_in_flight`, `_config_ops_in_flight`, `_auto_reconnecting`, `_user_disconnecting`, `_pending_detail_fetches`). Um botão que "não faz nada" quase sempre é uma dessas marcações presa.

## Build empacotado (`console=False`)

`sys.stdout`/`sys.stderr` são `None` no `.exe`. `main.py` instala streams nulas de fallback e captura toda exceção não tratada (main thread, threads secundárias e mensagens do próprio Qt) via `logging`, gravando em `logs/`. Ao adicionar código novo em qualquer slot/callback, não é preciso envolver tudo em `try/except` só por precaução — mas também não use `print()` para depuração (vira um no-op silencioso no `.exe`); use o `logging` já configurado.

## Bugs corrigidos nesta sessão (histórico, não repetir)

1. **App fechava sozinho segundos após conectar**: exceção não tratada em algum slot, combinada com `sys.stderr is None` no build `--windowed`, podia encerrar o processo sem log nenhum. Corrigido com streams nulas de fallback + `sys.excepthook`/`threading.excepthook`/`qInstallMessageHandler` em `main.py`.
2. **Status "conectado" (verde) mesmo após falha reportada**: `RasdialManager` matava o `rasdial.exe` no timeout do lado cliente, mas isso não cancelava a discagem em andamento no serviço RAS — a conexão podia terminar de estabelecer minutos depois, e o `VpnMonitor` (fonte de verdade) mostrava conectado. Corrigido: `connect()` agora cancela (`/disconnect` best-effort) quando o timeout estoura, para que a falha reportada seja verdadeira.
3. **"Conectar" sem efeito depois de editar uma VPN (exigia reiniciar o app)**: editar/excluir uma VPN conectada desconecta como efeito colateral (`Set-VpnConnection` exige isso) fora do `ConnectionService`; com `auto_reconnect` ativo, o monitor confundia essa queda com uma queda real e disparava reconexão automática concorrente com a própria edição — podendo deixar `_connect_ops_in_flight` preso atrás de um diálogo de credenciais aberto (e possivelmente oculto, se a janela estava minimizada/na bandeja). Corrigido com `_config_ops_in_flight` (suprime auto-reconnect durante edição/exclusão) + `widget.set_busy(True)` cobrindo o `update` + `bring_to_foreground()` antes de diálogos de credencial abertos por um fluxo assíncrono.
4. **Troca de tema claro/escuro não tinha efeito nenhum**: `AppSettings.theme` era persistido mas nunca lido para estilizar a `QApplication`. Implementado `utils/theme.py` (`apply_theme`), chamado no startup e ao salvar Configurações.
