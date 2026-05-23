<?xml version='1.0' encoding='UTF-8'?>
<userScreen>
  <screenName>RULEFRM1</screenName>
  <screenType>W</screenType>
  <templateScreen>Y</templateScreen>
  <formType>F</formType>
  <langID>en-us</langID>
  <screenFormat>U</screenFormat>
  <screenDesc>Rules Demo</screenDesc>
  <screenData>
    <screenDesc>Rules Demo</screenDesc>
    <screenFormat>U</screenFormat>
    <version>0</version>
    <screenDefinition definitionVersion="2">
      <title>Rules Demo</title>
      <newForm>awdForm</newForm>
      <class>dstTheme</class>
      <screenURL></screenURL>
      <includeList>
        <jsFile>awdForm.js</jsFile>
      </includeList>
      <linkList/>
      <customRules>(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // MEMO visible_when STAT == "R"
    awdForm[(stat === "R") ? "show" : "hide"]("MEMO");

    // MEMO required_when STAT == "R"
    awdForm.setRequired("MEMO", stat === "R");

    // ACCT enabled_when STAT in ["A", "P"]
    awdForm[((stat === "A") || (stat === "P")) ? "enable" : "disable"]("ACCT");

    // BATC default_when STAT == "A"
    if ((stat === "A") &amp;&amp; awdForm.isEmpty("BATC")) {
      awdForm.setValue("BATC", "BATCH-AUTO");
    }

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
</customRules>
      <customProperties></customProperties>
      <page index="0">
        <title>Rules Demo</title>
        <width>740</width>
        <height>335</height>
        <transformVariables></transformVariables>
        <dataDictionary>
          <fieldType>select</fieldType>
          <id>STAT_0</id>
          <name>STAT</name>
          <sequence></sequence>
          <label>Status</label>
          <class></class>
          <dataDictionary>STAT</dataDictionary>
          <externalDataDictionary></externalDataDictionary>
          <options>
            <row>
              <listValue>A</listValue>
              <listName>Active</listName>
            </row>
            <row>
              <listValue>R</listValue>
              <listName>Rejected</listName>
            </row>
            <row>
              <listValue>P</listValue>
              <listName>Pending</listName>
            </row>
          </options>
          <rootName></rootName>
          <helpText></helpText>
          <tabIndex>0</tabIndex>
          <required>N</required>
          <routingList>N</routingList>
          <buttonLabel>Label</buttonLabel>
          <labelPosition></labelPosition>
          <top>20</top>
          <left>20</left>
          <width>200</width>
        </dataDictionary>
        <dataDictionary>
          <fieldType>textInput</fieldType>
          <id>MEMO_1</id>
          <name>MEMO</name>
          <sequence></sequence>
          <label>Rejection memo</label>
          <class></class>
          <dataDictionary>MEMO</dataDictionary>
          <externalDataDictionary></externalDataDictionary>
          <default></default>
          <fieldFormat>Alphabetic</fieldFormat>
          <decimals>0</decimals>
          <length>200</length>
          <mask></mask>
          <maskOverride>N</maskOverride>
          <helpText></helpText>
          <tabIndex>1</tabIndex>
          <required>N</required>
          <readOnly>N</readOnly>
          <password>N</password>
          <allowSmartControl>Y</allowSmartControl>
          <labelPosition></labelPosition>
          <top>90</top>
          <left>20</left>
          <width>200</width>
        </dataDictionary>
        <dataDictionary>
          <fieldType>textInput</fieldType>
          <id>ACCT_2</id>
          <name>ACCT</name>
          <sequence></sequence>
          <label>Account</label>
          <class></class>
          <dataDictionary>ACCT</dataDictionary>
          <externalDataDictionary></externalDataDictionary>
          <default></default>
          <fieldFormat>Alphabetic</fieldFormat>
          <decimals>0</decimals>
          <length>10</length>
          <mask></mask>
          <maskOverride>N</maskOverride>
          <helpText></helpText>
          <tabIndex>2</tabIndex>
          <required>N</required>
          <readOnly>N</readOnly>
          <password>N</password>
          <allowSmartControl>Y</allowSmartControl>
          <labelPosition></labelPosition>
          <top>160</top>
          <left>20</left>
          <width>200</width>
        </dataDictionary>
        <dataDictionary>
          <fieldType>textInput</fieldType>
          <id>BATC_3</id>
          <name>BATC</name>
          <sequence></sequence>
          <label>Batch</label>
          <class></class>
          <dataDictionary>BATC</dataDictionary>
          <externalDataDictionary></externalDataDictionary>
          <default></default>
          <fieldFormat>Alphabetic</fieldFormat>
          <decimals>0</decimals>
          <length>6</length>
          <mask></mask>
          <maskOverride>N</maskOverride>
          <helpText></helpText>
          <tabIndex>3</tabIndex>
          <required>N</required>
          <readOnly>N</readOnly>
          <password>N</password>
          <allowSmartControl>Y</allowSmartControl>
          <labelPosition></labelPosition>
          <top>230</top>
          <left>20</left>
          <width>200</width>
        </dataDictionary>
      </page>
    </screenDefinition>
  </screenData>
  <publicLink>N</publicLink>
</userScreen>
