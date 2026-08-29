# MENTIROSO — MVP

Juego social de conocimiento futbolístico + bluff, multijugador y en tiempo real.
Este es el **MVP funcional** (Fases 1-10 del plan de desarrollo), jugable de punta a punta.

## Cómo correrlo

```bash
cd backend
pip install -r requirements.txt --break-system-packages   # o usá un venv
python -m app.db.seed        # siembra ~20 jugadores reales de prueba
uvicorn app.main:app --reload --port 8000
```

Abrí `http://localhost:8000` — el propio FastAPI sirve el frontend estático.
Para probar multijugador, abrí varias pestañas / dispositivos y unite con el código de sala.

Correr los tests del motor de juego y de filtros:

```bash
cd backend
python -m pytest app/tests/ -v
```

29 tests, todos pasando: reglas de turno, puntaje, demostración, timeouts de AFK,
y el traductor de filtros → queries.

---

## Reglas confirmadas (definidas junto con el usuario)

Estas decisiones **reemplazan/completan** los puntos que el documento original
dejaba abiertos:

1. **Turno estrictamente secuencial y rotativo.** A → B → C → A...
2. **Sin "pasar".** En tu turno solo hay dos acciones: `declare` (subir) o `mentiroso`.
3. **MENTIROSO** solo lo puede decir quien tiene el turno, y siempre apunta
   al jugador que hizo la declaración inmediatamente anterior (nunca a uno de más atrás).
4. **Puntos fijos ±1**, sin escalar por la cantidad declarada (decisión explícita
   del usuario, distinta de lo que se había sugerido inicialmente).
5. **Demostración sin feedback en vivo**: se cargan las N respuestas (se puede
   borrar/reescribir) y recién al terminar (botón o timeout) se revela qué
   estuvo bien y qué mal.
6. **Duplicados** normalizados (sin acentos/mayúsculas) se rechazan al tipear.
7. **Todo o nada**: si declaró 20 y demuestra 19 válidas, es fallo total.

### Decisiones que agregué yo (no estaban explícitas) y por qué

- **¿Quién arranca la ronda siguiente?** Rota siempre una posición
  (round-robin fijo), independientemente de quién ganó/perdió el desafío
  anterior. Es lo más simple y lo más "justo" — nadie puede evitar ser el
  que abre categoría evitando perder.
- **AFK / timeout en tu turno**, ya que no existe "pasar":
  - Si sos el primero en hablar en la ronda → se te fuerza la declaración
    mínima configurada (no podés "regalar" la ronda quedándote callado).
  - Si ya había una declaración previa → se te fuerza un MENTIROSO
    automático (no requiere inventarte un número).
  - Ver `engine/game.py::handle_betting_timeout`.
- **Timeout durante la demostración**: se cierra con lo que se haya
  cargado hasta ese momento. Por la regla de "todo o nada", casi siempre
  es un fallo automático salvo que hayas justo completado el cupo.
- **La primera categoría de la partida** la arma el anfitrión (todavía no
  hay "turno" definido en ese momento). De ahí en más, la arma quien tiene
  el turno, como pedía el documento original.

---

## Qué se ocultó a propósito (Punto 6 del documento)

La cantidad real de respuestas válidas de una categoría **nunca** viaja al
cliente durante la partida — ni siquiera a quien la está armando (para no
darle ventaja informativa cuando le toque declarar). Se calcula server-side
una sola vez (`filters/query_builder.py::validate_category`) solo para
rechazar categorías imposibles (`< min_answers`).

## Filtros incluidos en el MVP

Elegidos por dar la mayor combinación de categorías jugables con datos
objetivamente verificables, dejando afuera lo subjetivo (posición, "estilo
de juego") para no generar disputas:

- **Títulos**: Champions, Mundial, Libertadores, Copa América, Eurocopa
- **Premios individuales**: Balón de Oro, The Best, Bota de Oro
- **Nacionalidad**
- **Club** (alguna vez / actualmente)
- **Estado**: activo / retirado

El DSL (`filters/dsl.py`) ya soporta `min_count` en logros (para "ganó 2+
Champions" a futuro) sin necesidad de migrar el esquema.

---

## Arquitectura

```
backend/app/
├── engine/          # Game Engine puro, sin FastAPI ni DB (Fase 3)
│   ├── states.py    # GamePhase (máquina de estados)
│   ├── models.py    # dataclasses: Player, Declaration, RoundRecord...
│   ├── game.py       # MentirosoGame: toda la lógica de reglas
│   └── errors.py
├── db/
│   ├── models.py    # SQLAlchemy: Player, Club, Achievement genérico...
│   ├── database.py
│   └── seed.py      # ~20 jugadores reales de prueba
├── filters/
│   ├── dsl.py             # DSL tipado (Pydantic) para construir categorías
│   └── query_builder.py    # DSL -> sets de player_ids, SIN SQL dinámico
├── rooms/
│   └── manager.py    # Salas en memoria (Fase 16, un solo proceso)
├── schemas.py         # Pydantic: valida TODO mensaje entrante por WS/REST
├── main.py            # FastAPI: REST + WebSocket, timers, autoritativo
└── tests/             # 29 tests (motor + filtros)

frontend/
└── index.html         # Alpine.js + Tailwind (CDN) + WebSocket nativo, un solo archivo
```

**Servidor autoritativo real**: el motor de juego es la única fuente de
verdad sobre si una jugada es válida. El cliente nunca decide nada — todo
mensaje entrante pasa primero por un schema Pydantic (`schemas.py`) y
después por el `MentirosoGame`, que levanta excepciones tipadas
(`engine/errors.py`) si la acción no es válida en ese momento.

**El traductor de filtros nunca arma SQL con strings**: cada tipo de
condición del DSL tiene una función de resolución predefinida y
whitelisteada en `query_builder.py` que devuelve un `set[int]`; las
condiciones se combinan en Python (unión/intersección/complemento), nunca
concatenando queries.

---

## Qué queda afuera del MVP (a propósito)

Ranking/ELO, matchmaking, chat, reconexión con recuperación de sesión más
allá de "marcarte como desconectado", estadísticas persistentes, animaciones,
y — como se acordó explícitamente — cualquier mitigación anti-googleo (no
tiene sentido optimizar para eso jugando entre amigos; sí sería un tema
si en el futuro se agrega matchmaking/ranking).

## Próximos pasos sugeridos (Fase 11+)

1. Persistir el historial de rondas (`RoundRecord`) en DB para estadísticas
   futuras (Punto 19) — hoy vive solo en memoria dentro de `MentirosoGame.history`.
2. Reconexión real: hoy un jugador desconectado se marca `connected=False`
   pero no hay gracia period ni recuperación de turno si el AFK ocurre
   por corte de red y no por inacción real.
3. Si se corre con más de un worker de uvicorn, mover el estado de
   `RoomManager` a Redis (hoy es todo en memoria de un solo proceso).
4. Ampliar la base de datos de jugadores (hoy son ~20 de prueba) desde una
   fuente más completa, respetando el mismo esquema.
