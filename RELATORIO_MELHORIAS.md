# Relatorio de melhorias e correcoes - VPN Manager

Data da revisao: 2026-07-22

## Escopo da analise

Foi feita uma revisao estatica de todo o codigo do projeto `vpn_manager`, incluindo:

- ponto de entrada e ciclo de vida: `main.py`;
- janela principal e dialogos: `ui/*.py`;
- monitoramento, conexao, configuracao e persistencia: `core/*.py`;
- servicos assicronos: `services/*.py`;
- scripts PowerShell: `scripts/*.ps1`;
- empacotamento: `VPNManager.spec`;
- configuracoes, logs, icones, single instance e tema: `utils/*.py`.

Nao foi possivel executar `python -m compileall vpn_manager` nesta sessao porque o sandbox do Windows falhou ao iniciar novos processos PowerShell com `CreateProcessAsUserW failed: 1312`. Portanto, este documento e uma revisao de codigo, nao uma validacao em runtime.

## Resumo executivo

O aplicativo ja tem uma base boa para um gerenciador interno de VPNs: separa UI, servicos, core, scripts PowerShell, usa `QThread`/`QThreadPool`, evita bloquear a interface na maioria das operacoes e ja possui mitigacoes para timeouts e dialogos ocultos.

Os principais riscos restantes estao concentrados em quatro areas:

1. **Estados presos na UI**: alguns fluxos ainda podem deixar `_connect_ops_in_flight`, `_pending_detail_fetches`, `_config_ops_in_flight` ou `_user_disconnecting` inconsistentes quando uma worker falha antes de emitir sinal de conclusao.
2. **Fonte de verdade fragil para estado da VPN**: `rasdial` e parser de texto localizado sao usados para decidir se uma conexao esta ativa. Se `rasdial` falha, o app pode marcar todas como desconectadas e disparar logica incorreta.
3. **Gestao incompleta de phonebook/escopo**: o app le phonebooks de usuario/sistema e ate aceita diretorio PBK customizado, mas a conexao via `rasdial` nao passa `/phonebook`, entao pode conectar a entrada errada ou nem usar o PBK customizado.
4. **Seguranca e operacao corporativa**: senha em argumento de linha de comando, logs pouco estruturados, config/logs ao lado do executavel, falta de assinatura/instalador e ausencia de testes automatizados ainda impedem o nivel de produto corporativo profissional.

## Correcoes criticas recomendadas

### 1. Tratar excecoes inesperadas nas tarefas de conexao

Referencias:

- `services/connection_service.py:40`
- `ui/main_window.py:88`
- `ui/main_window.py:371`

Problema:

`_ConnectionTask.run()` nao envolve a operacao em `try/except`. Se `RasdialManager.connect()`, `disconnect()` ou `reconnect()` levantar uma excecao inesperada antes de retornar `CommandResult`, o sinal `finished` nao sera emitido. Nesse caso, a `MainWindow` nao executa `_on_operation_finished()`, e `_connect_ops_in_flight` pode ficar preso. Para o usuario, isso aparece como "clicar em conectar e nada acontecer".

Correcao recomendada:

- Envolver todo o corpo de `_ConnectionTask.run()` em `try/except Exception`.
- Sempre emitir `finished` com `success=False` em caso de excecao.
- Registrar `logger.exception(...)`.
- Considerar tambem um identificador de operacao (`operation_id`) para ignorar resultados antigos.

Exemplo de comportamento esperado:

- clique em conectar;
- erro inesperado em subprocesso;
- UI recebe `finished`;
- botao e estado transitorio sao liberados;
- usuario recebe mensagem clara.

Prioridade: **P0**.

### 2. Nao marcar todas as VPNs como desconectadas quando `rasdial` falhar

Referencias:

- `core/vpn_monitor.py:74`
- `core/vpn_monitor.py:76`
- `core/rasdial_manager.py:122`
- `core/rasdial_manager.py:126`

Problema:

`VpnMonitor.poll_once()` chama `list_active_connections()` e passa o resultado para `parse_active_connections()` sem verificar `active_result.success`. Se `rasdial` falhar por timeout, permissao, encoding, antivirus, PATH ou erro temporario do servico RAS, `parse_active_connections()` tende a retornar conjunto vazio. Isso faz o monitor interpretar todas as VPNs como desconectadas.

Impactos:

- reconexao automatica pode ser disparada indevidamente;
- conexoes ativas podem aparecer como desconectadas;
- o usuario pode clicar em conectar quando a VPN ja esta conectada;
- estados transitorios podem oscilar.

Correcao recomendada:

- Se `active_result.success` for `False`, preservar `_known_entries` e emitir `error_occurred`.
- Nao alterar status para `DISCONNECTED` quando a consulta de estado falhar.
- Exibir estado "desconhecido" ou manter o ultimo estado conhecido com aviso discreto.
- Registrar `return_code`, duracao e mensagem sanitizada.

Prioridade: **P0**.

### 3. Usar `/phonebook` no `rasdial` quando houver PBK customizado ou escopo ambiguo

Referencias:

- `core/pbk_parser.py:44`
- `core/pbk_parser.py:49`
- `core/rasdial_manager.py:116`
- `ui/main_window.py:439`

Problema:

O parser consegue ler um diretorio PBK customizado, mas `RasdialManager.connect()` executa apenas:

```text
rasdial.exe <nome>
```

Ele nao passa `/phonebook:<caminho>`. Na pratica, isso significa que o app pode **exibir** entradas do PBK customizado, mas ao conectar o Windows pode procurar a VPN nos phonebooks padrao do usuario/sistema. Se existir outra VPN com o mesmo nome, pode conectar a errada; se nao existir, pode falhar.

Tambem existe ambiguidade entre phonebook de usuario e de sistema: a UI mescla por `name.casefold()`, entao duas entradas com o mesmo nome em escopos diferentes nao podem ser representadas corretamente.

Correcao recomendada:

- Adicionar `phonebook_path` em `VpnEntry`.
- Fazer `PbkParser` preencher o caminho real do `.pbk`.
- Alterar `RasdialManager.connect/disconnect/list_active_connections` para aceitar `/phonebook:<path>` quando aplicavel.
- Trocar a chave interna de `name.casefold()` para uma chave composta: `scope + phonebook_path + name`.
- Na UI, exibir escopo quando houver nomes duplicados.

Prioridade: **P0** se PBK customizado for usado em producao; **P1** caso contrario.

### 4. Corrigir possiveis travamentos em busca de detalhes da VPN

Referencias:

- `services/vpn_config_service.py:61`
- `ui/main_window.py:458`
- `ui/main_window.py:466`

Problema:

`_DetailsTask.run()` nao captura excecoes. Embora `VpnConfigManager.get_details()` normalmente retorne `None` em falha, uma excecao inesperada em PowerShell, serializacao, objeto de retorno ou bug futuro pode impedir a emissao de `details_fetched`.

Impacto:

- `_pending_detail_fetches` fica com a VPN marcada;
- `widget.set_busy(True)` nao e revertido;
- editar passa a parecer travado ate reiniciar o app.

Correcao recomendada:

- Colocar `try/except Exception` em `_DetailsTask.run()`.
- Emitir `details_fetched(name, all_users, None)` em falha.
- Logar `logger.exception`.
- Adicionar timeout e mensagem visual "Nao foi possivel carregar detalhes".

Prioridade: **P0**.

### 5. Limpar `_user_disconnecting` no fim da operacao de desconexao

Referencias:

- `ui/main_window.py:91`
- `ui/main_window.py:274`
- `ui/main_window.py:341`
- `ui/main_window.py:371`

Problema:

`_user_disconnecting` e limpo apenas quando o monitor detecta uma transicao de conectado para desconectado. Se o `disconnect` falhar, se a VPN ja estiver desconectada, se o monitor perder a transicao, ou se `rasdial` falhar na consulta de estado, a marcacao pode ficar viva indefinidamente.

Impacto:

- quedas futuras podem ser classificadas como "pedidas pelo usuario";
- auto-reconnect pode deixar de funcionar para aquela VPN.

Correcao recomendada:

- Em `_on_operation_finished()`, se `operation == "disconnect"`, descartar a chave de `_user_disconnecting`.
- Se quiser preservar a semantica de "queda voluntaria", substituir o set por uma estrutura com TTL curto, por exemplo `dict[key] = monotonic_deadline`.

Prioridade: **P1**.

### 6. Implementar cancelamento real e backoff para conexoes demoradas

Referencias:

- `core/rasdial_manager.py:63`
- `core/rasdial_manager.py:82`
- `core/rasdial_manager.py:99`
- `ui/main_window.py:289`

Problema:

O timeout de `rasdial` cancela a tentativa com `/disconnect` em caso de timeout, o que e correto. Ainda assim, a UI nao oferece cancelamento explicito, nao mostra contagem de timeout e a reconexao automatica nao tem uma politica formal de tentativas/backoff.

Correcao recomendada:

- Adicionar botao "Cancelar" durante `CONNECTING`.
- Manter estado por operacao: `operation_id`, inicio, deadline, tentativa atual.
- Implementar backoff: 5s, 15s, 30s, 60s, limite maximo configuravel.
- Parar reconexao automatica apos N falhas consecutivas e avisar o usuario.
- Registrar motivo final: timeout, credencial, DNS, servidor inacessivel, VPN ja conectada, UAC cancelado etc.

Prioridade: **P1**.

## Melhorias importantes de arquitetura

### 7. Criar uma maquina de estados explicita por VPN

Hoje a UI combina:

- status vindo do monitor (`VpnStatus`);
- sets na `MainWindow`: `_connect_ops_in_flight`, `_config_ops_in_flight`, `_auto_reconnecting`, `_user_disconnecting`, `_pending_detail_fetches`;
- estados transitorios aplicados diretamente em `VpnEntry`.

Isso funciona, mas e facil deixar uma marcacao presa.

Recomendacao:

- Criar uma classe `VpnRuntimeState` por VPN com:
  - `status_observed`;
  - `operation_kind`;
  - `operation_id`;
  - `operation_started_at`;
  - `deadline`;
  - `last_error`;
  - `auto_reconnect_attempt`;
  - `source`: `monitor`, `user`, `auto_reconnect`, `config_change`.
- Centralizar transicoes em metodos como:
  - `begin_connect`;
  - `finish_connect`;
  - `begin_disconnect`;
  - `finish_disconnect`;
  - `observe_connected`;
  - `observe_disconnected`;
  - `begin_config_change`;
  - `finish_config_change`.

Beneficios:

- menos sets soltos;
- resultados atrasados podem ser ignorados por `operation_id`;
- testes de estado ficam simples;
- diagnostico de "preso" fica objetivo.

Prioridade: **P1**.

### 8. Separar fonte de verdade de "inventario" e "estado conectado"

Referencias:

- `core/pbk_parser.py:44`
- `core/vpn_monitor.py:72`

Hoje `VpnMonitor` le PBK e estado de conexao no mesmo ciclo. Para produto profissional, separar:

- `VpnInventoryService`: le phonebooks, escopos, detalhes, duplicidades, metadados;
- `VpnConnectionStateService`: le apenas status conectado/desconectado/interface/IP;
- `VpnOperationService`: executa conectar/desconectar/reconectar;
- `VpnConfigService`: cria/edita/remove.

Isso evita que falha em uma parte invalide tudo. Exemplo: se `rasdial` falhar, ainda e possivel mostrar inventario; se PBK falhar, ainda e possivel preservar estados ativos conhecidos.

Prioridade: **P1**.

### 9. Considerar API RAS nativa em vez de parsear saida de `rasdial`

Referencias:

- `core/rasdial_manager.py:126`

`parse_active_connections()` depende da estrutura textual do `rasdial`, que e localizada e nao contratual. Para uma ferramenta corporativa, e melhor usar uma fonte estruturada:

- Windows RAS API via `ctypes`/`pywin32`: `RasEnumConnections`, `RasGetConnectStatus`, `RasDial`, `RasHangUp`;
- ou PowerShell estruturado onde for confiavel;
- ou WMI/Network Adapter para complementar IP/interface.

Beneficios:

- status real de `CONNECTING`, `AUTHENTICATING`, `CONNECTED`, `DISCONNECTED`;
- erros numericos RAS oficiais;
- cancelamento mais confiavel;
- menos dependencia de idioma do Windows.

Prioridade: **P1**.

### 10. Evitar `QThreadPool.globalInstance()` para conexoes

Referencia:

- `services/connection_service.py:92`

O `ConnectionService` usa o pool global do Qt. Em apps maiores, o pool global pode ser usado por outras tarefas, gerando starvation ou concorrencia dificil de diagnosticar.

Recomendacao:

- Criar `QThreadPool()` proprio para conexoes.
- Definir `setMaxThreadCount()` pequeno e intencional, por exemplo 2 ou 3.
- Opcional: limitar uma operacao por VPN no proprio service, nao apenas na UI.

Prioridade: **P2**.

## PowerShell e configuracao de VPN

### 11. Timeout de operacoes elevadas pode deixar processo elevado rodando

Referencias:

- `core/powershell_runner.py:68`
- `core/powershell_runner.py:94`
- `core/powershell_runner.py:97`
- `scripts/_elevate.ps1:13`

Problema:

Quando ha elevacao, o processo Python espera o PowerShell wrapper `_elevate.ps1`, que por sua vez faz `Start-Process -Verb RunAs -Wait`. Se o timeout do Python estourar, ele mata o wrapper, mas o processo elevado pode continuar executando sem que o app acompanhe o resultado.

Correcao recomendada:

- Gerar `operation_id` no input JSON.
- Fazer o script elevado escrever progresso/resultado em arquivo conhecido.
- Em timeout, informar "resultado desconhecido" e forcar refresh do inventario.
- Considerar timeout maior para operacoes com UAC ou uma UI propria de "aguardando permissao".
- Evitar tratar timeout elevado como falha definitiva se a operacao pode continuar.

Prioridade: **P1**.

### 12. `_elevate.ps1` deve usar o executavel PowerShell resolvido pelo app

Referencia:

- `scripts/_elevate.ps1:13`

O wrapper chama literalmente `powershell.exe`. O Python ja resolve `POWERSHELL_EXE`, mas esse valor nao e reaproveitado dentro do script. Em ambientes corporativos com PATH restrito, redirecionamento 32/64 bits, AppLocker ou hardening, isso pode falhar.

Recomendacao:

- Passar o caminho do executavel PowerShell para `_elevate.ps1`.
- Ou usar `$PSHOME\powershell.exe`.
- Registrar caminho usado no log.

Prioridade: **P2**.

### 13. Validar parametros antes de chamar cmdlets

Referencias:

- `scripts/add_vpn.ps1:19`
- `scripts/update_vpn.ps1:27`
- `ui/vpn_edit_dialog.py:133`
- `ui/route_list_dialog.py:65`

Hoje nome, servidor e tipo de tunel sao basicamente validados pelos cmdlets. Para UX melhor:

- validar caracteres invalidos no nome da VPN;
- validar servidor como FQDN/IP ou permitir explicitamente valores internos;
- validar tamanho maximo de nome e servidor;
- validar se `L2tp` exige chave pre-compartilhada/certificado;
- validar se rotas IPv6 sao suportadas pelo fluxo real do Windows usado;
- bloquear rotas duplicadas entre escopos quando houver colisoes.

Prioridade: **P2**.

### 14. Suportar propriedades corporativas avancadas

O modelo atual cobre:

- nome;
- servidor;
- tipo de tunel;
- split tunneling;
- rotas.

Para gestao profissional, considerar adicionar:

- metodo de autenticacao: EAP, MSCHAPv2, certificado, smart card;
- `AuthenticationMethod`, `EncryptionLevel`, `RememberCredential`;
- DNS suffix;
- metrica de interface;
- proxy por VPN quando aplicavel;
- L2TP pre-shared key;
- Always On VPN / Device Tunnel / User Tunnel, se o ambiente usar;
- importacao/exportacao de perfis.

Prioridade: **P2/P3**, dependendo do ambiente.

## Seguranca

### 15. Evitar senha em argumento de linha de comando

Referencia:

- `core/rasdial_manager.py:116`

Problema:

Quando usuario e senha sao fornecidos, o app chama `rasdial.exe` com a senha como argumento. Em Windows, argumentos de processo podem ser visiveis para ferramentas de diagnostico, EDR, logs de auditoria, dumps e outros processos com permissao adequada.

Recomendacao:

- Preferir Windows Credential Manager/RAS credentials nativas e chamar `rasdial` sem senha.
- Avaliar RAS API nativa para passar credenciais por estrutura em memoria.
- Se continuar usando `rasdial`, documentar o risco e limitar o uso de credenciais manuais.
- Reduzir retencao em memoria: limpar referencias de senha apos uso quando possivel.

Prioridade: **P1** para ambiente corporativo sensivel.

### 16. Sanitizacao de logs deve mascarar segredos, nao apenas remover quebras de linha

Referencia:

- `utils/helpers.py:22`

`sanitize_for_log()` so remove `\r` e `\n`. Recomenda-se:

- mascarar padroes `password=`, `senha=`, `pwd=`, `token=`, `secret=`;
- mascarar valores conhecidos temporariamente quando houver credencial pendente;
- impedir log acidental de argumentos completos de subprocesso;
- criar testes especificos para sanitizacao.

Prioridade: **P1**.

### 17. `has_saved_credentials()` le a senha inteira a cada refresh

Referencias:

- `core/credential_store.py:70`
- `core/credential_store.py:91`
- `ui/main_window.py:229`

Problema:

A cada atualizacao da lista, a UI chama `credential_store.has_saved_credentials(entry.name)`, que internamente chama `load_credentials()` e le o blob da senha. Isso aumenta exposicao em memoria e custo de chamada.

Recomendacao:

- Implementar metodo que verifique existencia sem decodificar senha, se possivel.
- Ou manter cache curto de existencia invalidado por salvar/esquecer credenciais.
- Carregar senha somente no momento de conectar.

Prioridade: **P2**.

## UI/UX para evitar percepcao de "preso"

### 18. Mostrar progresso real da operacao

Hoje o usuario ve "Conectando", mas nao ve:

- ha quanto tempo esta tentando;
- timeout configurado;
- se esta aguardando UAC;
- se esta aguardando credenciais;
- se esta tentando reconectar automaticamente;
- qual tentativa do backoff esta rodando.

Recomendacao:

- Exibir subtitulo por VPN: "Conectando... 8s / timeout 30s".
- Trocar botoes por "Cancelar" durante conexao.
- Mostrar badge "Reconexao automatica 2/5".
- Adicionar painel de detalhes da ultima falha.

Prioridade: **P1**.

### 19. Melhorar fluxo de credenciais

Referencias:

- `ui/main_window.py:329`
- `ui/main_window.py:408`
- `ui/credentials_dialog.py:44`

Fluxo atual:

1. tenta conectar com credenciais salvas do app, se existirem;
2. se falhar com mensagem parecida com credencial, pede usuario/senha;
3. tenta de novo.

Riscos:

- se `rasdial` esperar entrada interativa, o usuario aguarda ate timeout;
- erros localizados podem nao bater com `_CREDENTIAL_ERROR_HINTS`;
- codigo RAS especifico seria mais confiavel do que texto.

Recomendacao:

- Detectar erro por codigo RAS quando possivel, especialmente 691.
- Se nao houver credencial salva no app nem credencial RAS conhecida, oferecer pedir credenciais antes da primeira tentativa.
- Permitir editar credenciais salvas pelo menu sem precisar falhar uma conexao.
- Nao deixar "Salvar minhas credenciais" marcado por padrao em ambientes sensiveis; tornar configuravel por politica.

Prioridade: **P1/P2**.

### 20. Bloquear duplicidade de operacoes de adicionar/configurar

Referencias:

- `ui/main_window.py:450`
- `ui/main_window.py:505`

`_open_add_vpn_dialog()` nao marca nenhuma operacao em andamento nem desabilita a action "Adicionar VPN". E possivel abrir/adicionar repetidamente enquanto uma criacao anterior ainda esta em andamento.

Recomendacao:

- Criar `_global_config_operation_in_flight` ou estado por nome tambem para add.
- Desabilitar "Adicionar VPN" durante criacao.
- Exibir progresso no status bar.
- Em sucesso ou falha, liberar sempre.

Prioridade: **P2**.

### 21. Melhorar mensagens de erro de `rasdial`

Hoje a mensagem amigavel usa stdout/stderr sanitizado. Para suporte corporativo, mapear codigos RAS comuns:

- 691: usuario/senha invalidos;
- 628/629: conexao encerrada pelo remoto;
- 633: porta/dispositivo ja em uso;
- 651/789/809: erro de rede, L2TP/IPsec, firewall/NAT;
- 868: DNS/servidor nao resolvido;
- timeout local do app.

Recomendacao:

- Extrair codigo numerico da saida;
- mapear para mensagem curta e acao sugerida;
- salvar codigo bruto no log.

Prioridade: **P2**.

## Monitoramento, desempenho e estabilidade

### 22. Evitar PowerShell por VPN dentro do polling

Referencias:

- `core/vpn_monitor.py:104`
- `core/vpn_monitor.py:116`
- `core/vpn_config_manager.py:105`
- `scripts/get_local_ip.ps1:19`

O monitor consulta IP interno chamando PowerShell por VPN conectada, ainda que com cache de 30s. Em maquinas com muitas VPNs, PowerShell pode ser pesado e gerar atraso no ciclo do monitor.

Recomendacao:

- Consultar todos os IPs de uma vez em um unico script;
- ou usar API Python/Windows para interfaces;
- ou deixar IP interno sob demanda no painel de detalhes;
- separar polling de status e polling de IP.

Prioridade: **P2**.

### 23. Encerramento do monitor deve respeitar operacoes bloqueantes

Referencia:

- `ui/main_window.py:576`

`_shutdown_monitor()` espera 3 segundos. Se o monitor estiver dentro de `rasdial` ou PowerShell, a thread pode continuar alem disso.

Recomendacao:

- Definir flag de parada cooperativa;
- impedir novo poll quando stop solicitado;
- aguardar no maximo `command_timeout + margem` ou encerrar com log claro;
- evitar destruir objetos Qt enquanto a thread ainda roda.

Prioridade: **P1**.

### 24. Logging diario nao troca de arquivo a meia-noite

Referencias:

- `utils/logger.py:14`
- `utils/logger.py:36`
- `ui/log_window.py:56`

O arquivo de log e escolhido no startup por data. Se o app ficar aberto virando a meia-noite, o `RotatingFileHandler` continua gravando no arquivo do dia anterior, enquanto `LogWindow` procura o arquivo do dia corrente.

Recomendacao:

- Usar `TimedRotatingFileHandler` com rotacao diaria;
- ou recriar handler quando a data mudar;
- fazer `LogWindow` mostrar o arquivo realmente ativo pelo logger.

Prioridade: **P2**.

### 25. `LogWindow` carrega o arquivo inteiro a cada refresh

Referencias:

- `ui/log_window.py:74`
- `ui/log_window.py:78`

Com 2 MB por arquivo isso e aceitavel, mas para diagnostico maior e melhor:

- ler apenas o tail incremental;
- permitir selecionar arquivo antigo;
- botao "Copiar diagnostico" com versao, config sanitizada, ultimas linhas e ambiente.

Prioridade: **P3**.

## Persistencia, instalacao e operacao corporativa

### 26. Mover config/logs para `%LOCALAPPDATA%` em build instalado

Referencias:

- `utils/constants.py:16`
- `utils/constants.py:22`
- `utils/constants.py:23`

No build PyInstaller, `CONFIG_DIR` e `LOGS_DIR` ficam ao lado do executavel. Isso e bom para modo portatil, mas ruim para instalacao em `Program Files`, onde usuario comum nao deve escrever.

Recomendacao:

- Suportar dois modos:
  - portatil: config/logs ao lado do exe;
  - instalado: `%LOCALAPPDATA%\VPNManager\config` e `%LOCALAPPDATA%\VPNManager\logs`.
- Detectar por variavel, argumento ou arquivo marcador.
- Documentar politica.

Prioridade: **P1** para distribuicao corporativa.

### 27. Criar instalador e assinatura de codigo

O projeto tem spec do PyInstaller, mas para ambiente profissional recomenda-se:

- MSI/MSIX ou instalador via Intune/SCCM;
- assinatura Authenticode;
- versao em metadata do executavel;
- icone, publisher, product name;
- uninstall limpo;
- politica de atualizacao.

Prioridade: **P2**.

### 28. Fortalecer single instance

Referencia:

- `utils/single_instance.py:41`

Se `QLocalServer.listen()` falhar, o app apenas loga warning e continua. Isso pode abrir multiplas instancias sem protecao.

Recomendacao:

- Usar `QLockFile` como fallback;
- se a instancia unica for requisito, falhar de forma explicita;
- incluir usuario/sessao no nome do servidor se necessario.

Prioridade: **P3**.

## Dados e modelo de dominio

### 29. Corrigir colisao de VPNs com mesmo nome

Referencias:

- `core/pbk_parser.py:49`
- `core/vpn_config_manager.py:118`

Hoje `get_all_vpn_entries()` sobrescreve entradas por `entry.key()`, que e apenas `name.casefold()`. Como o parser le usuario e sistema, uma VPN de sistema pode sobrescrever uma VPN de usuario com mesmo nome.

Recomendacao:

- Usar chave composta;
- detectar duplicidade e exibir na UI;
- bloquear operacoes ambiguas;
- passar escopo/phonebook para operacoes.

Prioridade: **P1**.

### 30. Enriquecer `VpnEntry`

Referencia:

- `core/models.py`

Adicionar campos:

- `id` ou chave composta estavel;
- `phonebook_path`;
- `scope_label`;
- `source`;
- `last_seen_at`;
- `observed_error`;
- `ras_error_code`;
- `interface_alias`;
- `gateway`;
- `dns_suffix`;
- `routes_summary`.

Prioridade: **P2**.

## Testes recomendados

Atualmente nao ha testes automatizados no projeto.

### 31. Testes unitarios

Adicionar testes para:

- `PbkParser`:
  - encoding UTF-8/CP1252;
  - secoes duplicadas;
  - user/system;
  - PBK customizado;
  - arquivo invalido.
- `RasdialManager.parse_active_connections()`:
  - sem conexoes;
  - uma conexao;
  - multiplas conexoes;
  - saida localizada;
  - saida inesperada.
- `RouteListDialog`:
  - CIDR valido;
  - duplicados;
  - default route bloqueada;
  - IPv6, se suportado.
- `SettingsManager`:
  - JSON invalido;
  - clamp;
  - campos desconhecidos.
- `credential_store` com mock de `advapi32`.

Prioridade: **P1**.

### 32. Testes de estado da MainWindow com fakes

Criar fakes para:

- `ConnectionService`;
- `VpnConfigService`;
- `VpnMonitor`;
- `CredentialStore`.

Cenarios essenciais:

- conectar falha e libera `_connect_ops_in_flight`;
- conectar falha por credencial e abre dialogo;
- dialogo cancelado libera estado;
- `details_fetched` com `None` libera widget;
- excecao em details libera widget;
- disconnect falho limpa `_user_disconnecting`;
- auto-reconnect nao dispara durante config;
- add/update/delete sempre liberam busy.

Prioridade: **P1**.

### 33. Testes de integracao em Windows

Em uma VM Windows de CI/manual:

- criar VPN fake com `Add-VpnConnection`;
- listar PBK;
- conectar a servidor invalido e validar timeout/cancelamento;
- validar UAC cancelado para all-users;
- editar/excluir VPN conectada;
- validar logs e ausencia de crash;
- validar build PyInstaller.

Prioridade: **P2**.

## Roadmap sugerido

### Fase 1 - estabilizar bugs de "preso"

1. Adicionar `try/except` em `_ConnectionTask` e `_DetailsTask`.
2. Verificar `active_result.success` no monitor antes de mudar status.
3. Limpar `_user_disconnecting` no fim de disconnect.
4. Adicionar `operation_id` para conexoes.
5. Adicionar testes de estado com fakes.

### Fase 2 - corrigir phonebook/escopo

1. Adicionar `phonebook_path` e chave composta.
2. Passar `/phonebook` ao `rasdial`.
3. Exibir duplicidades na UI.
4. Revisar comportamento de PBK customizado.

### Fase 3 - melhorar seguranca e UX

1. Evitar senha em linha de comando.
2. Melhorar fluxo de credenciais.
3. Implementar cancelar conexao.
4. Adicionar backoff de auto-reconnect.
5. Mapear codigos RAS comuns.

### Fase 4 - profissionalizar distribuicao

1. Config/logs em `%LOCALAPPDATA%` para modo instalado.
2. Instalador MSI/MSIX.
3. Assinatura de codigo.
4. Diagnostico exportavel.
5. Testes de integracao em VM Windows.

## Checklist objetivo de correcoes

- [ ] `_ConnectionTask.run()` sempre emite `finished`, inclusive em excecao.
- [ ] `_DetailsTask.run()` sempre emite `details_fetched`, inclusive em excecao.
- [ ] `VpnMonitor.poll_once()` preserva estado quando `rasdial` falha.
- [ ] `disconnect` limpa `_user_disconnecting` ao finalizar.
- [ ] Operacoes usam `operation_id` e ignoram sinais antigos.
- [ ] `rasdial` recebe `/phonebook` quando houver caminho PBK conhecido.
- [ ] Chave interna da VPN deixa de ser apenas nome case-insensitive.
- [ ] UI mostra progresso, timeout e botao cancelar.
- [ ] Auto-reconnect tem limite, backoff e mensagem clara.
- [ ] Logs mascaram segredos.
- [ ] Config/logs usam local adequado para build instalado.
- [ ] Testes unitarios cobrem parser, rasdial, settings e maquina de estados.
- [ ] Build PyInstaller e validado em Windows limpo.

## Conclusao

Para resolver o bug relatado de VPN que nao conecta e fica "presa", eu priorizaria primeiro as falhas de lifecycle das workers e do monitor: garantir que toda operacao sempre emita sinal de conclusao, que falha de `rasdial` nao seja interpretada como "todas desconectadas", e que os sets de controle da `MainWindow` sejam substituidos gradualmente por uma maquina de estados testavel.

Depois disso, a melhoria mais importante para confiabilidade real no Windows e corrigir o suporte a phonebook/escopo usando `/phonebook` e chave composta. Sem isso, o app pode mostrar uma VPN mas pedir ao `rasdial` para conectar outra fonte de dados.
