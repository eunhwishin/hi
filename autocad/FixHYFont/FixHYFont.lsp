;;; ===========================================================================
;;;  FixHYFont.lsp  -  깨지는 HY 글꼴(영문 이름)을 한글 글꼴 이름으로 자동 변경
;;; ---------------------------------------------------------------------------
;;;  문제: 다른 PC에서 받은 도면의 문자스타일 글꼴이 "HY헤드라인M" 대신
;;;        "HYHeadLine-Medium" 으로 저장되어 있어 글자가 ??? 로 깨짐.
;;;  해결: 문자스타일 / MTEXT 내부 글꼴코드에 들어있는 영문 글꼴 이름을
;;;        아래 *FixHY-FontMap* 에 정의된 한글 이름으로 바꿔 줌.
;;;
;;;  명령어
;;;    FIXHYFONT       : 현재 도면 수정 (클릭 한 번)
;;;    FIXHYFONTALL    : 현재 열려있는 모든 도면 수정
;;;    FIXHYFONTBATCH  : 폴더를 선택하면 폴더 안의 DWG 를 일괄 수정/저장
;;;
;;;  자동 실행
;;;    이 파일을 APPLOAD > "시작하기 세트(Startup Suite)" 에 넣어 두면
;;;    도면을 열 때마다 자동으로 FIXHYFONT 가 실행됨 (*FixHY-AutoRun* = T).
;;; ===========================================================================

(vl-load-com)

;;; ---------------------------------------------------------------------------
;;;  설정
;;; ---------------------------------------------------------------------------
;;  (도면에 저장된 영문 글꼴 이름 . 바꿀 한글 글꼴 이름)
;;  다른 HY 글꼴도 같은 현상이 있으면 아래 주석(;)을 풀거나 줄을 추가하면 됨.
(setq *FixHY-FontMap*
  '(("HYHeadLine-Medium"    . "HY헤드라인M")
    ;; ("HYGothic-Extra"       . "HY견고딕")
    ;; ("HYGothic-Medium"      . "HY중고딕")
    ;; ("HYGraphic-Medium"     . "HY그래픽M")
    ;; ("HYMyeongJo-Extra"     . "HY견명조")
    ;; ("HYSinMyeongJo-Medium" . "HY신명조")
   )
)

;;  T  : 파일이 로드될 때(=도면을 열 때, 시작하기 세트 등록 시) 자동 실행
;;  nil: 명령어로만 실행
(if (null *FixHY-AutoRun*) (setq *FixHY-AutoRun* T))

;;  일괄처리 시 원본을 .bak 로 백업할지 여부
(setq *FixHY-MakeBackup* T)

;;  한글 문자셋 (HANGUL_CHARSET)
(setq *FixHY-Charset* 129)

;;; ---------------------------------------------------------------------------
;;;  공통 함수
;;; ---------------------------------------------------------------------------
(defun FixHY:Lookup (name / hit)
  (if (and name (/= name ""))
    (foreach pair *FixHY-FontMap*
      (if (and (null hit) (= (strcase (car pair)) (strcase name)))
        (setq hit (cdr pair))
      )
    )
  )
  hit
)

;;  문자스타일 수정 -> 바뀐 개수 반환
(defun FixHY:FixStyles (doc / cnt tf bold ital cs pf new)
  (setq cnt 0)
  (vlax-for st (vla-get-TextStyles doc)
    (setq tf nil bold nil ital nil cs nil pf nil)
    (if (and (not (vl-catch-all-error-p
                    (vl-catch-all-apply 'vla-GetFont
                      (list st 'tf 'bold 'ital 'cs 'pf))))
             (setq new (FixHY:Lookup tf)))
      (if (not (vl-catch-all-error-p
                 (vl-catch-all-apply 'vla-SetFont
                   (list st new bold ital *FixHY-Charset* pf))))
        (progn
          (setq cnt (1+ cnt))
          (princ (strcat "\n  [문자스타일] " (vla-get-Name st) " : " tf " -> " new))
        )
        (princ (strcat "\n  [실패] 문자스타일 " (vla-get-Name st) " 변경 불가"))
      )
    )
  )
  cnt
)

;;  MTEXT 서식코드 \f<글꼴>| 안의 글꼴 이름 치환 -> (새문자열 . 치환횟수)
(defun FixHY:ReplaceFontCode (str old new / key pos n)
  (setq key (strcase (strcat "\\f" old "|")) pos 0 n 0)
  (while (setq pos (vl-string-search key (strcase str) pos))
    (setq str (strcat (substr str 1 (+ pos 2))
                      new
                      (substr str (+ pos 3 (strlen old))))
          pos (+ pos 2 (strlen new))
          n   (1+ n))
  )
  (cons str n)
)

(defun FixHY:FixMTextString (str / res total)
  (setq total 0)
  (foreach pair *FixHY-FontMap*
    (setq res   (FixHY:ReplaceFontCode str (car pair) (cdr pair))
          str   (car res)
          total (+ total (cdr res)))
  )
  (cons str total)
)

;;  모든 블록(모형/배치/블록정의)의 MTEXT, 다중 지시선 내부 글꼴코드 수정
(defun FixHY:FixMTexts (doc / cnt res old)
  (setq cnt 0)
  (vlax-for blk (vla-get-Blocks doc)
    (if (= (vla-get-IsXRef blk) :vlax-false)
      (vlax-for obj blk
        (cond
          ((= (vla-get-ObjectName obj) "AcDbMText")
           (setq old (vla-get-TextString obj)
                 res (FixHY:FixMTextString old))
           (if (and (> (cdr res) 0)
                    (not (vl-catch-all-error-p
                           (vl-catch-all-apply 'vla-put-TextString
                             (list obj (car res))))))
             (setq cnt (1+ cnt)))
          )
          ((= (vla-get-ObjectName obj) "AcDbMLeader")
           (if (not (vl-catch-all-error-p
                      (setq old (vl-catch-all-apply 'vla-get-TextString (list obj)))))
             (progn
               (setq res (FixHY:FixMTextString old))
               (if (and (> (cdr res) 0)
                        (not (vl-catch-all-error-p
                               (vl-catch-all-apply 'vla-put-TextString
                                 (list obj (car res))))))
                 (setq cnt (1+ cnt)))
             )
           )
          )
        )
      )
    )
  )
  cnt
)

;;  도면(Document 또는 ObjectDBX 문서) 하나 처리 -> (스타일수 . MTEXT수)
(defun FixHY:FixDoc (doc / s m)
  (setq s (FixHY:FixStyles doc)
        m (FixHY:FixMTexts doc))
  (cons s m)
)

(defun FixHY:RunActive (doc quiet / res)
  (setq res (FixHY:FixDoc doc))
  (if (> (+ (car res) (cdr res)) 0)
    (progn
      (vl-catch-all-apply 'vla-Regen (list doc acAllViewports))
      (princ (strcat "\n[FixHYFont] " (vla-get-Name doc)
                     " : 문자스타일 " (itoa (car res)) "개, MTEXT "
                     (itoa (cdr res)) "개 글꼴 수정 완료."))
    )
    (if (not quiet)
      (princ (strcat "\n[FixHYFont] " (vla-get-Name doc) " : 수정할 글꼴이 없습니다.")))
  )
  res
)

;;; ---------------------------------------------------------------------------
;;;  명령어 1 : 현재 도면
;;; ---------------------------------------------------------------------------
(defun c:FIXHYFONT (/ doc)
  (setq doc (vla-get-ActiveDocument (vlax-get-acad-object)))
  (vla-StartUndoMark doc)
  (FixHY:RunActive doc nil)
  (vla-EndUndoMark doc)
  (princ)
)

;;; ---------------------------------------------------------------------------
;;;  명령어 2 : 열려 있는 모든 도면
;;; ---------------------------------------------------------------------------
(defun c:FIXHYFONTALL ()
  (vlax-for doc (vla-get-Documents (vlax-get-acad-object))
    (FixHY:RunActive doc nil)
  )
  (princ "\n[FixHYFont] 열린 도면을 저장(QSAVE)해야 수정 내용이 파일에 반영됩니다.")
  (princ)
)

;;; ---------------------------------------------------------------------------
;;;  명령어 3 : 폴더 일괄 처리 (ObjectDBX)
;;; ---------------------------------------------------------------------------
(defun FixHY:BrowseFolder (msg / sh fld path)
  (setq sh (vlax-create-object "Shell.Application"))
  (if sh
    (progn
      (setq fld (vl-catch-all-apply 'vlax-invoke-method
                  (list sh 'BrowseForFolder 0 msg 0)))
      (if (and fld (not (vl-catch-all-error-p fld)))
        (setq path (vlax-get-property (vlax-get-property fld 'Self) 'Path)))
      (vlax-release-object sh)
    )
  )
  path
)

(defun FixHY:ListDwg (dir sub / res)
  (setq dir (vl-string-right-trim "\\/" dir))
  (foreach f (vl-directory-files dir "*.dwg" 1)
    (setq res (cons (strcat dir "\\" f) res)))
  (if sub
    (foreach d (vl-directory-files dir nil -1)
      (if (not (member d '("." "..")))
        (setq res (append res (FixHY:ListDwg (strcat dir "\\" d) T))))))
  res
)

(defun FixHY:GetDbx (/ ver)
  (setq ver (atoi (substr (getvar "ACADVER") 1 2)))
  (vla-GetInterfaceObject (vlax-get-acad-object)
    (if (< ver 16) "ObjectDBX.AxDbDocument"
                   (strcat "ObjectDBX.AxDbDocument." (itoa ver))))
)

(defun FixHY:FindOpenDoc (path / hit)
  (vlax-for d (vla-get-Documents (vlax-get-acad-object))
    (if (= (strcase (vla-get-FullName d)) (strcase path)) (setq hit d)))
  hit
)

(defun c:FIXHYFONTBATCH (/ dir sub files dbx opened res ok nFix nSkip nFail bak)
  (setq dir (FixHY:BrowseFolder "글꼴을 수정할 DWG 폴더를 선택하세요"))
  (if (null dir) (progn (princ "\n취소되었습니다.") (exit)))
  (initget "Yes No")
  (setq sub (= (getkword "\n하위 폴더도 포함할까요? [Yes/No] <No>: ") "Yes"))
  (setq files (FixHY:ListDwg dir sub)
        nFix 0 nSkip 0 nFail 0)
  (if (null files) (progn (princ "\nDWG 파일이 없습니다.") (exit)))
  (princ (strcat "\n" (itoa (length files)) "개 도면 처리 시작..."))
  (setq dbx (FixHY:GetDbx))
  (foreach f files
    (princ (strcat "\n" f))
    (cond
      ;; 이미 열려있는 도면은 직접 수정 (저장은 사용자가)
      ((setq opened (FixHY:FindOpenDoc f))
       (setq res (FixHY:RunActive opened T))
       (if (> (+ (car res) (cdr res)) 0) (setq nFix (1+ nFix)) (setq nSkip (1+ nSkip)))
       (princ "\n  (열려있는 도면 - 직접 저장하세요)")
      )
      ((vl-catch-all-error-p (vl-catch-all-apply 'vla-Open (list dbx f)))
       (princ "\n  [실패] 열 수 없음 (읽기전용/다른 사용자 사용 중?)")
       (setq nFail (1+ nFail))
      )
      (T
       (setq res (FixHY:FixDoc dbx))
       (if (> (+ (car res) (cdr res)) 0)
         (progn
           (if *FixHY-MakeBackup*
             (progn
               (setq bak (strcat (vl-filename-directory f) "\\"
                                 (vl-filename-base f) ".bak"))
               (if (findfile bak) (vl-file-delete bak))
               (vl-file-copy f bak)
             )
           )
           (setq ok (not (vl-catch-all-error-p
                           (vl-catch-all-apply 'vla-SaveAs (list dbx f)))))
           (if ok
             (progn (setq nFix (1+ nFix))
                    (princ (strcat "\n  -> 저장 완료 (스타일 " (itoa (car res))
                                   ", MTEXT " (itoa (cdr res)) ")")))
             (progn (setq nFail (1+ nFail))
                    (princ "\n  [실패] 저장 불가 (읽기전용?)"))
           )
         )
         (setq nSkip (1+ nSkip))
       )
      )
    )
  )
  (vlax-release-object dbx)
  (princ (strcat "\n\n[FixHYFont] 완료 - 수정 " (itoa nFix)
                 "개 / 변경없음 " (itoa nSkip) "개 / 실패 " (itoa nFail) "개"))
  (princ)
)

;;; ---------------------------------------------------------------------------
;;;  로드 시 자동 실행
;;; ---------------------------------------------------------------------------
(if *FixHY-AutoRun*
  (vl-catch-all-apply 'FixHY:RunActive
    (list (vla-get-ActiveDocument (vlax-get-acad-object)) T))
)

(princ "\n[FixHYFont] 로드됨. 명령: FIXHYFONT(현재도면) / FIXHYFONTALL(열린도면 전체) / FIXHYFONTBATCH(폴더 일괄)")
(princ)
