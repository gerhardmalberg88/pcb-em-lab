<Qucs Schematic 26.1.1>
<Properties>
  <View=0,0,1250,750,0.9,0,0>
  <Grid=10,10,1>
  <DataSet=network.dat>
  <DataDisplay=network.dpl>
  <OpenDisplay=0>
  <Script=network.m>
  <RunScript=0>
  <showFrame=0>
</Properties>
<Symbol>
</Symbol>
<Components>
  <SPfile PCB 1 400 220 -26 -65 0 0 "network.s2p" 1 "rectangular" 0 "linear" 0 "open" 0 "2" 0>
  <Pac P1 1 200 280 18 -26 0 1 "1" 1 "100 Ohm" 1 "0 dBm" 0 "100 MHz" 0 "26.85" 0 "true" 0 "false" 0>
  <Pac P2 1 600 280 18 -26 0 1 "2" 1 "100 Ohm" 1 "0 dBm" 0 "100 MHz" 0 "26.85" 0 "true" 0 "false" 0>
  <GND * 1 200 340 0 0 0 0>
  <GND * 1 400 340 0 0 0 0>
  <GND * 1 600 340 0 0 0 0>
  <.SP SP1 1 200 420 0 47 0 0 "lin" 1 "100 MHz" 1 "800 MHz" 1 "8" 1 "no" 0 "1" 0 "2" 0 "no" 0 "no" 0>
  <Eqn Eqn1 1 200 570 -20 10 0 0 "reflection=dB(S[1,1])" 1 "transmission=dB(S[2,1])" 1 "yes" 0>
</Components>
<Wires>
  <200 220 370 220 "input" 240 190 0 "">
  <430 220 600 220 "output" 490 190 0 "">
  <200 220 200 250 "" 0 0 0 "">
  <600 220 600 250 "" 0 0 0 "">
  <200 310 200 340 "" 0 0 0 "">
  <400 250 400 340 "" 0 0 0 "">
  <600 310 600 340 "" 0 0 0 "">
</Wires>
<Diagrams>
  <Rect 800 500 360 260 3 #c0c0c0 1 00 1 1e8 1e8 8e8 1 -60 10 0 1 -1 0.5 1 315 0 225 1 0 0 "Frequency (Hz)" "Magnitude (dB)" "">
    <"reflection" #cc3333 2 3 0 0 0>
    <"transmission" #2244cc 2 3 0 0 0>
  </Rect>
</Diagrams>
<Paintings>
  <Text 120 60 12 #000000 0 "PCB EM Lab: differential-pair network\nTwo abstract differential wave ports; this is not a common-mode model.">
  <Text 800 560 12 #000000 0 "Blue: S21 (transmission)\nRed: S11 (reflection)">
</Paintings>
