'use client';

/**
 * @fileoverview The exhibits' islands: the verifier switch, and each
 * exhibit's state with its answer picks, probe switch and frame readout.
 *
 * Every value an exhibit shows is in the server's HTML. A block lists the
 * answers it shows in data-ans and a packet list its probe in data-pr, and
 * the exhibit's root shows the picked answer's and probe's with a style
 * rule keyed on them, as the Reel's stage shows one frame; the verifier is
 * the root's data-view, which the page's style sheet reads. A ringed
 * square or a turned answer's link elsewhere on the page names an exhibit
 * and an answer (data-exhibit, data-answer); following it shows that
 * answer with the tail. Only the frame readout renders values of its own:
 * the frame pointed at or tapped, from the replayed probes' frame tables,
 * through lib/sourced-text.tsx. An exhibit's groups of buttons are named by
 * a fixed word and the case id its heading shows, so no two groups on the
 * page share a name.
 */

import {createContext, useContext, useEffect, useMemo, useState} from 'react';
import type {PointerEvent, ReactNode, SyntheticEvent} from 'react';

import type {FrameState} from '@/lib/exhibits-codes';
import type {ReplayProbe} from '@/lib/exhibits-data';
import {CodeText, NumText, StrText} from '@/lib/sourced-text';

import {STATE_WORDS, VIEW_WORDS} from './words';
import type {View} from './words';

const VIEWS: readonly View[] = ['tail', 'alone'];
const KILLING: ReadonlySet<string> = new Set(['fp', 'fn']);

/** An exhibit: its case id, and the id of the element that shows it. */
interface Scope {
  readonly id: string;
  readonly named: string;
}

/**
 * A group's name: its word, and in an exhibit the case id after it. The
 * group names itself first (its aria-label, read through its own id), then
 * the heading's case id.
 */
function groupName(word: string, scope?: Scope) {
  if (scope === undefined) {
    return {'aria-label': word};
  }
  const own = `${scope.id}-${word.toLowerCase()}`;
  return {id: own, 'aria-label': word, 'aria-labelledby': `${own} ${scope.named}`};
}

interface SwitchProps {
  readonly view: View;
  readonly onChange: (view: View) => void;
  /** The exhibit the switch belongs to; none for the overview's. */
  readonly scope?: Scope;
}

/** The two verifiers as a pair of pressed buttons. */
export function ViewSwitch({view, onChange, scope}: SwitchProps): ReactNode {
  return (
    <div {...groupName('Verifier', scope)} className="xh-seg" role="group">
      {VIEWS.map((each) => (
        <button
          aria-pressed={view === each}
          key={each}
          onClick={() => onChange(each)}
          type="button"
        >
          {VIEW_WORDS[each]}
        </button>
      ))}
    </div>
  );
}

/** A frame under the pointer: its probe's place, its number and its state. */
interface Spot {
  readonly probe: number;
  readonly frame: number;
  readonly state: FrameState;
}

interface ExhibitState {
  readonly scope: Scope;
  readonly pick: number;
  readonly view: View;
  readonly probe: number;
  readonly spot: Spot | null;
  readonly setPick: (pick: number) => void;
  readonly setView: (view: View) => void;
  readonly setProbe: (probe: number) => void;
  readonly setSpot: (spot: Spot | null) => void;
}

const ExhibitContext = createContext<ExhibitState | null>(null);

function useExhibit(): ExhibitState {
  const state = useContext(ExhibitContext);
  if (state === null) {
    throw new Error('exhibits: a control outside its <ExhibitRoot>');
  }
  return state;
}

interface RootProps {
  /** The case id: the exhibit's address and the key its links name. */
  readonly id: string;
  readonly labelledBy: string;
  /** The id of the heading's case id, which names the exhibit's groups. */
  readonly named: string;
  readonly children: ReactNode;
}

/** An exhibit's root: its state, and the rule that shows one answer. */
export function ExhibitRoot({id, labelledBy, named, children}: RootProps): ReactNode {
  const [pick, setPick] = useState(0);
  const [view, setView] = useState<View>('tail');
  const [probe, setProbe] = useState(0);
  const [spot, setSpot] = useState<Spot | null>(null);

  useEffect(() => {
    const open = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const link = target?.closest<HTMLElement>('[data-exhibit]');
      if (link?.dataset['exhibit'] !== id) {
        return;
      }
      setPick(Number(link.dataset['answer'] ?? '0'));
      setView('tail');
      setSpot(null);
    };
    document.addEventListener('click', open);
    return () => document.removeEventListener('click', open);
  }, [id]);

  const value = useMemo(
    () => ({scope: {id, named}, pick, view, probe, spot, setPick, setView, setProbe, setSpot}),
    [id, named, pick, view, probe, spot],
  );
  const root = `[data-xh=${JSON.stringify(id)}]`;
  return (
    <ExhibitContext.Provider value={value}>
      <article aria-labelledby={labelledBy} className="xh-ex" data-view={view} data-xh={id} id={id}>
        <style>
          {`${root} [data-ans]:not([data-ans~="${pick}"]),` +
            `${root} [data-pr]:not([data-pr="${probe}"]){display:none}`}
        </style>
        {children}
      </article>
    </ExhibitContext.Provider>
  );
}

/** The exhibit's verifier switch. */
export function ExhibitView(): ReactNode {
  const {scope, view, setView, setSpot} = useExhibit();
  return (
    <ViewSwitch
      onChange={(next) => {
        setView(next);
        setSpot(null);
      }}
      scope={scope}
      view={view}
    />
  );
}

/** One pressed button per item, labelled by server-rendered values. */
function Buttons({labels, name, at, choose}: {
  readonly labels: readonly ReactNode[];
  readonly name: string;
  readonly at: number;
  readonly choose: (index: number) => void;
}): ReactNode {
  const {scope} = useExhibit();
  return (
    <div {...groupName(name, scope)} className="xh-picks" role="group">
      {labels.map((label, index) => (
        <button aria-pressed={index === at} key={index} onClick={() => choose(index)} type="button">
          {label}
        </button>
      ))}
    </div>
  );
}

/** The answers of an exhibit with more than one. */
export function Picks({labels}: {readonly labels: readonly ReactNode[]}): ReactNode {
  const {pick, setPick, setSpot} = useExhibit();
  const choose = (index: number) => {
    setPick(index);
    setSpot(null);
  };
  return <Buttons at={pick} choose={choose} labels={labels} name="Answers" />;
}

/** The probe whose killing frames the packet list shows. */
export function ProbeSwitch({labels}: {readonly labels: readonly ReactNode[]}): ReactNode {
  const {probe, setProbe} = useExhibit();
  return <Buttons at={probe} choose={setProbe} labels={labels} name="Probe" />;
}

/**
 * The tapes: a frame cell (data-n, data-s) under a mouse or pen is read out
 * until the pointer leaves the tapes. A touch has no hover, so a tap reads
 * the cell out and keeps it; a touch that scrolls the page reads nothing.
 */
export function TapesArea({children}: {readonly children: ReactNode}): ReactNode {
  const {setSpot} = useExhibit();
  const read = (event: SyntheticEvent) => {
    const target = event.target instanceof Element ? event.target : null;
    const cell = target?.closest<HTMLElement>('[data-n]');
    const tape = cell?.closest<HTMLElement>('[data-p]');
    const state = cell?.dataset['s'];
    if (cell == null || tape == null || state === undefined) {
      return;
    }
    setSpot({
      probe: Number(tape.dataset['p']),
      frame: Number(cell.dataset['n']),
      state: state as FrameState,
    });
  };
  const hovers = (event: PointerEvent) => event.pointerType !== 'touch';
  return (
    <div
      className="xh-tapes"
      onClick={read}
      onPointerLeave={(event) => {
        if (hovers(event)) {
          setSpot(null);
        }
      }}
      onPointerOver={(event) => {
        if (hovers(event)) {
          read(event);
        }
      }}
    >
      {children}
    </div>
  );
}

interface ReadoutProps {
  readonly probes: readonly ReplayProbe[];
  /** What the line says with no frame read out, per answer and view. */
  readonly children: ReactNode;
}

/** The frame read out, as tshark's packet list prints it. */
export function FrameReadout({probes, children}: ReadoutProps): ReactNode {
  const {spot} = useExhibit();
  const probe = spot === null ? undefined : probes[spot.probe];
  const row = spot === null ? undefined : probe?.frame_rows[spot.frame - 1];
  return (
    <div aria-live="polite" className="xh-fd">
      <div hidden={row !== undefined}>{children}</div>
      {spot === null || probe === undefined || row === undefined ? null : (
        <p>
          <b>
            <StrText node={probe.probe_id} /> frame <NumText kind="int" node={row.n} />
          </b>{' '}
          (<CodeText kind="frame_kind" node={row.kind} /> <StrText node={row.name} />):{' '}
          <StrText node={row.source} /> &rarr; <StrText node={row.destination} />{' '}
          <StrText node={row.protocol} /> <StrText node={row.info} />.{' '}
          <span className={KILLING.has(spot.state) ? 'dn' : undefined}>
            {STATE_WORDS[spot.state]}
          </span>
          .
        </p>
      )}
    </div>
  );
}
