# OMEGA INFINITY — time-multiplexing externo

Cliente de PC + servidor de la placa Tiny Tapeout + ejemplos y pruebas.

Empieza con [el tutorial completo en español](OMEGA_INFINITY_TUTORIAL_ES.md).

Prueba inmediata, sin placa ni dependencias adicionales:

```bash
python run_sat_hw.py self-test --backend sim
python run_sat_hw.py evaluate examples/demo_300k/demo.cnf --backend sim --assignment examples/demo_300k/assignment.txt --cross-check
```

El paquete procesa la evaluación de una CNF por ventanas de 16 gates y conserva
los resultados en la PC. El comando `solve` hace la búsqueda SAT en la PC y,
cuando encuentra una candidata, verifica su evaluación mediante esas ventanas.

Perfil exacto: `omega16-constant52-v1`. El Verilog original, sin cambios, está en
`rtl_reference/`. Su SHA-256 está en `RTL_PROFILE.json`.

Validación realizada: software y controlador de placa con un doble de SDK.
La puesta en marcha con el ASIC físico comienza con `probe` y `self-test`.
