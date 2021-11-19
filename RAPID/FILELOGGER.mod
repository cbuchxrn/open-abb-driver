MODULE FILELOGGER

    VAR string FileLocation:="HOME:test.txt";
    VAR iodev File;

    VAR robtarget position;
    VAR jointtarget joints;

    PERS tooldata currentTool;    
    PERS wobjdata currentWobj;    
    
    PROC main()
	VAR clock timer;
	VAR string cData;
	VAR string jData;
	VAR string date;
	VAR string time;

	Open FileLocation, File \Append;

	date := CDate();
	time := CTime();

	! read cartesian coordinate
	!----------------------------------------------------------------
	position := CRobT(\Tool:=currentTool \WObj:=currentWObj);
	cData := "# 0 ";
	cData := cData + date + " " + time + " ";
	cData := cData + NumToStr(ClkRead(timer),2) + " ";
	cData := cData + NumToStr(position.trans.x,1) + " ";
	cData := cData + NumToStr(position.trans.y,1) + " ";
	cData := cData + NumToStr(position.trans.z,1) + " ";
	cData := cData + NumToStr(position.rot.q1,3) + " ";
	cData := cData + NumToStr(position.rot.q2,3) + " ";
	cData := cData + NumToStr(position.rot.q3,3) + " ";
	cData := cData + NumToStr(position.rot.q4,3);	
	!----------------------------------------------------------------

	Write File, cData+", "\NoNewLine;

	! read joint angles
	!----------------------------------------------------------------
	joints := CJointT();
	jData := "# 1 ";
	jData := jData + NumToStr(ClkRead(timer),2) + " ";
	jData := jData + NumToStr(joints.robax.rax_1,2) + " ";
	jData := jData + NumToStr(joints.robax.rax_2,2) + " ";
	jData := jData + NumToStr(joints.robax.rax_3,2) + " ";
	jData := jData + NumToStr(joints.robax.rax_4,2) + " ";
	jData := jData + NumToStr(joints.robax.rax_5,2) + " ";
	jData := jData + NumToStr(joints.robax.rax_6,2);
	!----------------------------------------------------------------

	Write File, jData+", ";

 	Close File;
    ENDPROC

ENDMODULE